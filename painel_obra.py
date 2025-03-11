import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import datetime
import requests
import json
import os
import subprocess
from flask_caching import Cache
import time

# Instala as dependências caso não estejam instaladas
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from geopy.geocoders import Nominatim
    import flask_caching
except ModuleNotFoundError:
    print("📌 Instalando dependências...")
    subprocess.check_call(["pip", "install", "gspread", "oauth2client", "geopy", "flask-caching"])
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from geopy.geocoders import Nominatim

# API do OpenWeatherMap
API_KEY = "034f2255b5ce05778c180823514a93fb"
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

# Lista inicial de municípios
municipios_disponiveis = ["Utinga", "Bom Jesus da Serra", "Poções", "Iramaia", "Ibiquera", 
                         "Wagner", "Bonito", "Morro do Chapéu", "Pombas", "Planalto", "João Neiva"]

# Definição de cores para os canteiros e disciplinas
cores_canteiros = {
    "Tabocas": "#007bff",
    "Planova": "#ff4d4d",
    "Enind": "#505050",
    "Engetécnica": "#505050",
    "Folga": "#ffcc00"
}

cores_disciplinas = {
    "Produção - LT": "#ff0000",
    "Produção - SE": "#ff8c00",
    "Segurança": "#008000",
    "Fornecimento": "#00008b",
    "Geologia": "#8b4513",
    "Saúde": "#f8f9fa",
    "Qualidade": "#add8e6",
    "Liderança": "#ffff00"  # Adicionada nova disciplina com cor amarela
}

# Inicialização de variáveis globais
client = None
creds = None

# Criar o app Dash
app = dash.Dash(__name__, suppress_callback_exceptions=True)
server = app.server  # Necessário para deploy em serviços como Render

# Configurar o cache
cache = Cache(app.server, config={
    'CACHE_TYPE': 'filesystem',
    'CACHE_DIR': 'cache-directory',
    'CACHE_DEFAULT_TIMEOUT': 300  # 5 minutos
})

# Variável para controle da última atualização dos dados
ultima_atualizacao = 0
dados_atuais = pd.DataFrame()
coordenadas_cache = {}
previsoes_cache = {}
previsoes_timestamp = {}

def inicializar_google_sheets():
    """Inicializa a conexão com o Google Sheets"""
    global client, creds
    try:
        credenciais_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
        
        # Configurar autenticação com o Google Sheets
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(credenciais_json, scope)
        client = gspread.authorize(creds)
        
        print("✅ Conexão com Google Sheets inicializada com sucesso!")
        return True
    except KeyError:
        print("❌ ERRO: Variável de ambiente GOOGLE_CREDENTIALS não encontrada!")
        return False
    except Exception as e:
        print(f"❌ Erro ao inicializar conexão com Google Sheets: {e}")
        return False

@cache.memoize(timeout=300)  # Cache por 5 minutos
def carregar_dados(force_refresh=False):
    """Carrega os dados da planilha do Google Sheets com cache"""
    global client, creds, ultima_atualizacao, dados_atuais
    
    # Verifica se precisamos atualizar ou se podemos usar os dados em memória
    tempo_atual = time.time()
    if not force_refresh and not dados_atuais.empty and (tempo_atual - ultima_atualizacao) < 300:
        return dados_atuais
    
    try:
        # Verificar se o cliente já está inicializado
        if client is None:
            if not inicializar_google_sheets():
                return pd.DataFrame()
        
        # Definir o ID da planilha
        SHEET_ID = os.environ.get("SHEET_ID", "1x3YfPAut6jONtLzP0eITD0O4USV3Ils6VLhO3PTpOg8")
        SHEET_NAME = "painelobra"  # Nome da aba da planilha
        
        # Abrir a planilha e carregar os dados
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        dados = sheet.get_all_records()  # Retorna os dados da planilha como dicionário
        
        # Converter para DataFrame
        df = pd.DataFrame(dados)
        
        # Pré-processamento dos dados
        if "Município" in df.columns and "UF" in df.columns:
            # Pré-carrega as coordenadas para todos os municípios
            for _, row in df.iterrows():
                if pd.notna(row["Município"]) and pd.notna(row["UF"]):
                    chave = f"{row['Município']}-{row['UF']}"
                    if chave not in coordenadas_cache:
                        coordenadas_cache[chave] = obter_coordenadas(row["Município"], row["UF"])
                        time.sleep(0.1)  # Pequeno delay para não sobrecarregar o serviço de geocoding
            
            # Adiciona as coordenadas ao DataFrame
            df["Latitude"] = df.apply(
                lambda row: coordenadas_cache.get(f"{row['Município']}-{row['UF']}", None) 
                if pd.notna(row["Município"]) and pd.notna(row["UF"]) else None, 
                axis=1
            )
        
        # Atualiza as variáveis globais
        dados_atuais = df
        ultima_atualizacao = tempo_atual
        
        print(f"✅ Dados carregados com sucesso! {len(df)} registros encontrados.")
        return df
    except gspread.exceptions.APIError as e:
        print(f"❌ Erro de API do Google Sheets: {e}")
        # Tentar renovar as credenciais
        if inicializar_google_sheets():
            return carregar_dados(force_refresh=True)
        return pd.DataFrame()
    except Exception as e:
        print(f"❌ Erro ao carregar dados do Google Sheets: {e}")
        return pd.DataFrame()

def obter_previsao(municipios):
    """Função para obter previsão do tempo com cache"""
    global previsoes_cache, previsoes_timestamp
    
    if not municipios:
        return {}
    
    tempo_atual = time.time()
    previsoes = {}
    municipios_consultar = []
    
    # Verifica quais cidades precisam ser atualizadas
    for cidade in municipios:
        # Se a cidade estiver no cache e a previsão for recente (menos de 30 minutos)
        if cidade in previsoes_cache and (tempo_atual - previsoes_timestamp.get(cidade, 0)) < 1800:
            previsoes[cidade] = previsoes_cache[cidade]
        else:
            municipios_consultar.append(cidade)
    
    # Consulta a API apenas para cidades que precisam ser atualizadas
    for cidade in municipios_consultar:
        try:
            url = f"{BASE_URL}?q={cidade}&appid={API_KEY}&lang=pt_br&units=metric"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                dados = response.json()
                previsao = {
                    "Temperatura": f"{dados['main']['temp']:.1f}°C",
                    "Condição": dados['weather'][0]['description'].capitalize(),
                    "Umidade": f"{dados['main']['humidity']}%"
                }
                previsoes[cidade] = previsao
                previsoes_cache[cidade] = previsao
                previsoes_timestamp[cidade] = tempo_atual
            else:
                previsoes[cidade] = {"Erro": f"Não foi possível obter a previsão para {cidade}."}
        except Exception as e:
            print(f"Erro ao obter previsão para {cidade}: {e}")
            previsoes[cidade] = {"Erro": f"Erro ao obter previsão para {cidade}."}
    
    return previsoes

def semana_atual():
    """Função para calcular a semana do ano e intervalo de datas"""
    hoje = datetime.date.today()
    semana = hoje.isocalendar()[1]
    segunda = hoje - datetime.timedelta(days=hoje.weekday())
    sabado = segunda + datetime.timedelta(days=5)
    return f"Semana {semana} - {segunda.strftime('%d/%m/%Y')} até {sabado.strftime('%d/%m/%Y')}"

def obter_coordenadas(municipio, uf):
    """Obtém as coordenadas geográficas do município e estado com cache."""
    chave = f"{municipio}-{uf}"
    
    # Se já temos as coordenadas no cache, retorna diretamente
    if chave in coordenadas_cache:
        return coordenadas_cache[chave]
    
    try:
        geolocator = Nominatim(user_agent="painel_obra")
        localizacao = geolocator.geocode(f"{municipio}, {uf}, Brasil", timeout=10)
        if localizacao:
            coordenadas_cache[chave] = localizacao.latitude
            return localizacao.latitude
        coordenadas_cache[chave] = None
        return None
    except Exception as e:
        print(f"Erro ao obter coordenadas para {municipio}, {uf}: {e}")
        coordenadas_cache[chave] = None
        return None

# Inicializa a conexão com o Google Sheets
inicializar_google_sheets()

def layout():
    """Função principal de layout"""
    df = carregar_dados()
    if df.empty:
        return html.Div([
            html.H1("Erro: Dados não disponíveis", 
                   style={"color": "red", "textAlign": "center"}),
            html.P("Verifique as variáveis de ambiente e a conexão com o Google Sheets.",
                  style={"textAlign": "center"}),
            html.Button("Tentar novamente", id="btn-reload", 
                       style={"margin": "20px auto", "display": "block"})
        ])
    
    return html.Div([
        # CSS para configurar a resolução padrão para 1920x1080
        html.Style("""
            html, body {
                width: 1920px;
                height: 1080px;
                margin: 0 auto;
                overflow: auto;
            }
            @media screen and (max-width: 1919px) {
                html, body {
                    transform-origin: top left;
                    transform: scale(calc(100vw / 1920));
                    height: calc(1080px * (100vw / 1920));
                }
            }
        """),
        
        # Widget de previsão do tempo
        html.Div([
            dcc.Dropdown(
                id="filtro_municipios",
                options=[{"label": cidade, "value": cidade} for cidade in municipios_disponiveis],
                placeholder="Selecione os municípios",
                multi=True,
                style={"width": "300px"}
            ),
            html.Div(id="widget_previsao")
        ], style={
            "position": "absolute",
            "top": "10px",
            "left": "10px",
            "backgroundColor": "#444",
            "padding": "10px",
            "borderRadius": "8px",
            "zIndex": "1000"
        }),
        
        html.H1("Painel de Controle da Obra - Asa Branca Transmissora de Energia", 
                style={"textAlign": "center", "color": "#333", 
                       "fontFamily": "Orbitron, sans-serif", "fontSize": "36px"}),
        
        html.H2(semana_atual(), 
                style={"textAlign": "center", "color": "#666", 
                       "fontSize": "24px", "marginBottom": "20px"}),
        
        # Seção de filtros e botão de atualização
        html.Div([
            dcc.Dropdown(
                id="filtro_disciplina",
                options=[{"label": d, "value": d} for d in df["Disciplina"].dropna().unique()],
                placeholder="Filtrar por disciplina",
                multi=True,
                style={"width": "25%"}
            ),
            dcc.Dropdown(
                id="filtro_local",
                options=[{"label": l, "value": l} for l in df["Local Atual"].dropna().unique()],
                placeholder="Filtrar por local",
                multi=True,
                style={"width": "25%"}
            ),
            dcc.Dropdown(
                id="filtro_empreiteira",
                options=[{"label": e, "value": e} for e in df["Empreiteira"].dropna().unique()],
                placeholder="Filtrar por empreiteira",
                multi=True,
                style={"width": "25%"}
            ),
            html.Button("Atualizar Dados", id="btn-update", 
                      style={"width": "15%", "backgroundColor": "#4CAF50", "color": "white", 
                             "padding": "10px", "border": "none", "borderRadius": "5px"})
        ], style={"display": "flex", "gap": "10px", "justifyContent": "center", "marginBottom": "20px"}),
        
        # Indicador de última atualização
        html.Div(id="status-atualizacao", style={"textAlign": "center", "marginBottom": "10px"}),
        
        # Armazenamento dos dados filtrados para evitar recarregamento
        dcc.Store(id="store-dados-filtrados"),
        
        # Quadro visual dos canteiros - ajustado para layouts maiores
        html.Div(id="quadro_canteiros", 
                 style={
                     "display": "flex", 
                     "gap": "20px", 
                     "justifyContent": "center", 
                     "flexWrap": "wrap", 
                     "padding": "20px",
                     "maxWidth": "1880px",
                     "margin": "0 auto"
                 }),
        
        # Interval para atualização automática dos dados (a cada 5 minutos)
        dcc.Interval(
            id='interval-component',
            interval=300*1000,  # 5 minutos em milissegundos
            n_intervals=0
        )
    ])

@app.callback(
    Output("widget_previsao", "children"),
    [Input("filtro_municipios", "value"),
     Input("interval-component", "n_intervals")]
)
def atualizar_previsao(municipios_selecionados, n_intervals):
    """Callback para atualizar widget de previsão do tempo"""
    if not municipios_selecionados:
        return html.Div("Selecione municípios para ver a previsão", 
                       style={"color": "white", "padding": "10px"})
    
    previsoes = obter_previsao(municipios_selecionados)
    return html.Div([
        html.Div([
            html.H4(cidade, style={"color": "white", "marginBottom": "10px"}),
            html.Div([
                html.P(f"Temperatura: {dados['Temperatura']}", style={"color": "white", "margin": "5px 0"}),
                html.P(f"Condição: {dados['Condição']}", style={"color": "white", "margin": "5px 0"}),
                html.P(f"Umidade: {dados['Umidade']}", style={"color": "white", "margin": "5px 0"})
            ] if "Erro" not in dados else
            html.P(dados["Erro"], style={"color": "red"})),
            html.Hr(style={"margin": "10px 0", "borderColor": "#666"})
        ]) for cidade, dados in previsoes.items()
    ])

@app.callback(
    [Output("store-dados-filtrados", "data"),
     Output("status-atualizacao", "children")],
    [Input("filtro_disciplina", "value"), 
     Input("filtro_local", "value"), 
     Input("filtro_empreiteira", "value"),
     Input("btn-update", "n_clicks"),
     Input("interval-component", "n_intervals")]
)
def filtrar_dados(filtro_disciplina, filtro_local, filtro_empreiteira, n_clicks, n_intervals):
    """Callback para filtrar os dados e armazenar no dcc.Store"""
    # Forçar atualização apenas se o botão foi clicado
    ctx = dash.callback_context
    button_clicked = False
    if ctx.triggered:
        input_id = ctx.triggered[0]['prop_id'].split('.')[0]
        if input_id == "btn-update":
            button_clicked = True
    
    df_filtrado = carregar_dados(force_refresh=button_clicked)
    
    if df_filtrado.empty:
        return {}, html.Div("Erro ao carregar dados", style={"color": "red"})
    
    # Aplica os filtros
    if filtro_disciplina:
        df_filtrado = df_filtrado[df_filtrado["Disciplina"].isin(filtro_disciplina)]
    if filtro_local:
        df_filtrado = df_filtrado[df_filtrado["Local Atual"].isin(filtro_local)]
    if filtro_empreiteira:
        df_filtrado = df_filtrado[df_filtrado["Empreiteira"].isin(filtro_empreiteira)]
    
    # Ordenar por latitude quando disponível
    if "Latitude" in df_filtrado.columns and df_filtrado["Latitude"].notna().any():
        df_com_lat = df_filtrado[df_filtrado["Latitude"].notna()].sort_values(by="Latitude", ascending=False)
        df_sem_lat = df_filtrado[df_filtrado["Latitude"].isna()]
        df_filtrado = pd.concat([df_com_lat, df_sem_lat])
    
    # Preparar os dados para o armazenamento
    dados_canteiros = []
    for canteiro in df_filtrado["Local Atual"].unique():
        df_canteiro = df_filtrado[df_filtrado["Local Atual"] == canteiro]
        
        # Verificar se há registros para este canteiro
        if df_canteiro.empty:
            continue
        
        empreiteira = df_canteiro["Empreiteira"].iloc[0] if not df_canteiro["Empreiteira"].isna().all() else "Folga"
        
        colaboradores = []
        for _, row in df_canteiro.iterrows():
            if pd.notna(row['Nome']) and pd.notna(row['Disciplina']):
                colaboradores.append({
                    "nome": row['Nome'],
                    "disciplina": row['Disciplina']
                })
        
        dados_canteiros.append({
            "canteiro": canteiro,
            "empreiteira": empreiteira,
            "colaboradores": colaboradores
        })
    
    # Formatando a mensagem de última atualização
    ultima_att = datetime.datetime.fromtimestamp(ultima_atualizacao).strftime('%d/%m/%Y %H:%M:%S')
    status = html.Div([
        html.Span("Última atualização: ", style={"fontWeight": "bold"}),
        html.Span(ultima_att),
        html.Span(" • ", style={"margin": "0 5px"}),
        html.Span(f"{len(dados_canteiros)} canteiros encontrados")
    ])
    
    return {"canteiros": dados_canteiros}, status

@app.callback(
    Output("quadro_canteiros", "children"),
    [Input("store-dados-filtrados", "data")]
)
def atualizar_quadro(dados):
    """Callback para atualizar o quadro de canteiros usando os dados filtrados armazenados"""
    if not dados or "canteiros" not in dados:
        return html.Div("Sem dados para exibir")
    
    cards = []
    
    for canteiro_data in dados["canteiros"]:
        canteiro = canteiro_data["canteiro"]
        empreiteira = canteiro_data["empreiteira"]
        cor_canteiro = cores_canteiros.get(empreiteira, "#d3d3d3")
        
        background_style = {
            "backgroundColor": cor_canteiro,
            "padding": "20px",
            "borderRadius": "12px",
            "color": "#fff",
            "width": "320px",
            "position": "relative",
            "minHeight": "200px",
            "boxShadow": "0 4px 6px rgba(0, 0, 0, 0.1)"
        }
        
        if empreiteira == "Folga":
            background_style.update({
                "backgroundImage": "url('https://static.vecteezy.com/ti/vetor-gratis/p1/13330130-a-vista-de-ferias-de-verao-na-praia-com-cadeira-de-praia-e-alguns-coqueiros-vetor.jpg')",
                "backgroundSize": "cover",
                "backgroundPosition": "center"
            })
        
        titulo_style = {
            "textAlign": "center",
            "color": "#000" if empreiteira in ["Folga", "Qualidade"] else "#fff",
            "fontSize": "24px",
            "fontFamily": "Orbitron, sans-serif",
            "backgroundColor": "rgba(50, 50, 50, 0.7)",
            "padding": "5px",
            "borderRadius": "8px",
            "marginBottom": "15px"
        }
        
        colaboradores_html = html.Ul([
            html.Li(
                f"{colaborador['nome']} - {colaborador['disciplina']}",
                style={
                    "backgroundColor": cores_disciplinas.get(colaborador['disciplina'], "#ddd"),
                    "color": "#000" if colaborador['disciplina'] in ["Saúde", "Qualidade", "Folga", "Liderança"] else "#fff",
                    "fontWeight": "bold",
                    "padding": "8px",
                    "borderRadius": "8px",
                    "fontSize": "20px",
                    "fontFamily": "Orbitron, sans-serif",
                    "marginBottom": "5px",
                    "listStyleType": "none"
                }
            ) for colaborador in canteiro_data["colaboradores"]
        ], style={"padding": "0", "margin": "0"})
        
        cards.append(html.Div([
            html.H3(f"{canteiro}" if empreiteira == "Folga" else f"{canteiro} - {empreiteira}", 
                   style=titulo_style),
            colaboradores_html
        ], style=background_style))
    
    return cards

@app.callback(
    Output("btn-reload", "children"),
    [Input("btn-reload", "n_clicks")]
)
def reload_data(n_clicks):
    """Callback para recarregar os dados quando o botão for clicado"""
    if n_clicks:
        inicializar_google_sheets()
        carregar_dados(force_refresh=True)
        return "Dados recarregados"
    return "Tentar novamente"

# Configurando layout do app
app.layout = layout()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run_server(host="0.0.0.0", port=port, debug=False)  # Debug False para produção