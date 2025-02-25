import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output
import datetime
import requests
import gspread
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ✅ Carregar credenciais diretamente da variável de ambiente do Render
try:
    credenciais_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])

    # ✅ Configurar autenticação com o Google Sheets
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credenciais_json, scope)
    client = gspread.authorize(creds)

    print("✅ Conexão com Google Sheets estabelecida com sucesso!")
except KeyError:
    print("❌ ERRO: Variável de ambiente 'GOOGLE_CREDENTIALS' não encontrada!")
except Exception as e:
    print(f"❌ Erro ao carregar dados do Google Sheets: {e}")

# API do OpenWeatherMap
API_KEY = "034f2255b5ce05778c180823514a93fb"  # Substitua pela sua chave da API
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
    "Qualidade": "#add8e6"
}

def carregar_dados():
    """Carrega os dados da planilha do Google Sheets"""
    try:
        # Configurar credenciais
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)

        # Abrir a planilha e carregar os dados
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        dados = sheet.get_all_records()  # Retorna os dados da planilha como dicionário

        # Converter para DataFrame
        return pd.DataFrame(dados)
    except Exception as e:
        print(f"Erro ao carregar dados do Google Sheets: {e}")
        # Se falhar, tenta carregar dados de backup ou retorna um DataFrame vazio
        return pd.DataFrame()

def obter_previsao(municipios):
    """Função para obter previsão do tempo"""
    if not municipios:
        return {}
        
    previsoes = {}
    for cidade in municipios:
        try:
            url = f"{BASE_URL}?q={cidade}&appid={API_KEY}&lang=pt_br&units=metric"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                dados = response.json()
                previsoes[cidade] = {
                    "Temperatura": f"{dados['main']['temp']:.1f}°C",
                    "Condição": dados['weather'][0]['description'].capitalize(),
                    "Umidade": f"{dados['main']['humidity']}%"
                }
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

# Criando o app Dash
app = dash.Dash(__name__)

def layout():
    """Função principal de layout"""
    df = carregar_dados()
    if df.empty:
        return html.Div([
            html.H1("Erro: Dados não disponíveis", 
                   style={"color": "red", "textAlign": "center"})
        ])
    
    return html.Div([
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
        
        # Seção de filtros
        html.Div([
            dcc.Dropdown(
                id="filtro_disciplina",
                options=[{"label": d, "value": d} for d in df["Disciplina"].dropna().unique()],
                placeholder="Filtrar por disciplina",
                multi=True,
                style={"width": "30%"}
            ),
            dcc.Dropdown(
                id="filtro_local",
                options=[{"label": l, "value": l} for l in df["Local Atual"].dropna().unique()],
                placeholder="Filtrar por local",
                multi=True,
                style={"width": "30%"}
            ),
            dcc.Dropdown(
                id="filtro_empreiteira",
                options=[{"label": e, "value": e} for e in df["Empreiteira"].dropna().unique()],
                placeholder="Filtrar por empreiteira",
                multi=True,
                style={"width": "30%"}
            )
        ], style={"display": "flex", "gap": "10px", "justifyContent": "center", "marginBottom": "20px"}),
        
        # Quadro visual dos canteiros
        html.Div(id="quadro_canteiros", 
                 style={"display": "flex", "gap": "20px", "justifyContent": "center", "flexWrap": "wrap", "padding": "20px"}),
    ])

@app.callback(
    Output("widget_previsao", "children"),
    [Input("filtro_municipios", "value")]
)
def atualizar_previsao(municipios_selecionados):
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
    Output("quadro_canteiros", "children"),
    [Input("filtro_disciplina", "value"), 
     Input("filtro_local", "value"), 
     Input("filtro_empreiteira", "value")]
)
def atualizar_quadro(filtro_disciplina, filtro_local, filtro_empreiteira):
    """Callback para atualizar o quadro de canteiros"""
    df_filtrado = carregar_dados()
    
    if df_filtrado.empty:
        return html.Div("Erro ao carregar dados", style={"color": "red"})
    
    if filtro_disciplina:
        df_filtrado = df_filtrado[df_filtrado["Disciplina"].isin(filtro_disciplina)]
    if filtro_local:
        df_filtrado = df_filtrado[df_filtrado["Local Atual"].isin(filtro_local)]
    if filtro_empreiteira:
        df_filtrado = df_filtrado[df_filtrado["Empreiteira"].isin(filtro_empreiteira)]
    
    canteiros = df_filtrado["Local Atual"].unique()
    cards = []
    
    for canteiro in canteiros:
        df_canteiro = df_filtrado[df_filtrado["Local Atual"] == canteiro]
        empreiteira = df_canteiro["Empreiteira"].iloc[0] if not df_canteiro.empty else "Folga"
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
                f"{row['Nome']} - {row['Disciplina']}",
                style={
                    "backgroundColor": cores_disciplinas.get(row['Disciplina'], "#ddd"),
                    "color": "#000" if row['Disciplina'] in ["Saúde", "Qualidade", "Folga"] else "#fff",
                    "fontWeight": "bold",
                    "padding": "8px",
                    "borderRadius": "8px",
                    "fontSize": "20px",
                    "fontFamily": "Orbitron, sans-serif",
                    "marginBottom": "5px",
                    "listStyleType": "none"
                }
            ) for _, row in df_canteiro.iterrows()
        ], style={"padding": "0", "margin": "0"})
        
        cards.append(html.Div([
            html.H3(f"{canteiro}" if empreiteira == "Folga" else f"{canteiro} - {empreiteira}", 
                   style=titulo_style),
            colaboradores_html
        ], style=background_style))
    
    return cards

# Configurando layout do app
app.layout = layout()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))  # Define a porta correta
    app.run_server(host="0.0.0.0", port=port, debug=True)