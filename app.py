import streamlit as st
import requests
import concurrent.futures
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import time
import pandas as pd

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="AcademiGraph Pro | Buscador Científico", 
    layout="wide", 
    page_icon="🎓"
)

# --- ESTILO VISUAL ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; border: none; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #1c83e1; color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. MOTORES DE BÚSQUEDA ---

def buscar_federado(materia, limite, email):
    resultados = []
    
    def buscar_oa():
        try:
            res = requests.get("https://api.openalex.org/works", 
                               params={"search": materia, "per-page": limite, "mailto": email}, timeout=10)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    doi_url = item.get("doi")
                    resultados.append({
                        "Fuente": "OpenAlex", "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": doi_url.replace("https://doi.org/", "") if doi_url else None
                    })
        except: pass

    def buscar_cr():
        try:
            res = requests.get("https://api.crossref.org/works", 
                               params={"query": materia, "rows": limite, "mailto": email}, timeout=10)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    autores = item.get("author", [])
                    autor = autores[0].get('family') if autores else "N/A"
                    resultados.append({
                        "Fuente": "Crossref", "Título": item.get("title", [""])[0],
                        "Autor": autor, "DOI": item.get("DOI")
                    })
        except: pass

    def buscar_uco():
        try:
            url = "https://mezquita.uco.es/primaws/rest/pub/pnxs"
            params = {"q": f"any,contains,{materia}", "limit": limite, "vid": "34CBUA_UCO:VU1", "tab": "Everything", "scope": "MyInst_and_CI", "inst": "34CBUA_UCO"}
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                for item in res.json().get("docs", []):
                    pnx = item.get("pnx", {})
                    disp = pnx.get("display", {})
                    doi = pnx.get("addata", {}).get("doi", [None])[0]
                    resultados.append({
                        "Fuente": "UCO", "Título": disp.get("title", [""])[0],
                        "Autor": disp.get("creator", ["N/A"])[0], "DOI": doi
                    })
        except: pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_cr)
        executor.submit(buscar_uco)
        
    return resultados

# --- 2. MOTOR DE RED (BIDIRECCIONAL) ---

def obtener_red_ss(doi, titulo, limite_red=3):
    refs, cits = [], []
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            p_id = data.get("paperId") if doi else data.get("data", [{}])[0].get("paperId")
            if p_id:
                # Referencias (Pasado)
                r_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/references", params={"limit":limite_red, "fields":"title"}, timeout=10)
                if r_res.status_code == 200:
                    refs = [i['citedPaper']['title'] for i in r_res.json().get('data', []) if i.get('citedPaper')]
                # Citas (Futuro)
                c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", params={"limit":limite_red, "fields":"title"}, timeout=10)
                if c_res.status_code == 200:
                    cits = [i['citingPaper']['title'] for i in c_res.json().get('data', []) if i.get('citingPaper')]
    except: pass
    return refs, cits

# --- 3. INTERFAZ STREAMLIT ---

st.title("🎓 AcademiGraph Pro")
st.markdown("Busca literatura científica y visualiza redes de citación bidireccionales.")

with st.sidebar:
    st.header("⚙️ Parámetros")
    user_email = st.text_input("Email (Polite Pool)", "investigador@ejemplo.com")
    n_results = st.slider("Resultados por buscador", 1, 10, 5)
    st.divider()
    st.info("Conectado a OpenAlex, Crossref, UCO y Semantic Scholar.")

query = st.text_input("Introduce el tema de investigación:", placeholder="Ej: Energías renovables en Córdoba")

if st.button("🚀 Iniciar Investigación"):
    if query:
        # FASE 1: BÚSQUEDA
        with st.status("Consultando fuentes federadas...", expanded=True) as s:
            data_base = buscar_federado(query, n_results, user_email)
            s.write(f"✅ {len(data_base)} artículos base encontrados.")
            
            # FASE 2: CONSTRUCCIÓN DE RED
            s.write("Mapeando conexiones científicas...")
            grafo = nx.DiGraph()
            progreso = st.progress(0)
            
            for i, art in enumerate(data_base):
                r_list, c_list = obtener_red_ss(art['DOI'], art['Título'])
                
                # Nodo central (Verde)
                grafo.add_node(art['Título'], color='#4CAF50', size=25)
                
                for r in r_list:
                    grafo.add_node(r, color='#ff4b4b', size=15) # Referencias (Rojo)
                    grafo.add_edge(art['Título'], r)
                for c in c_list:
                    grafo.add_node(c, color='#00aaff', size=15) # Citas (Azul)
                    grafo.add_edge(c, art['Título'])
                
                progreso.progress((i + 1) / len(data_base))
                time.sleep(1) # Respetar Rate Limit de Semantic Scholar

            s.update(label="Análisis finalizado", state="complete")

        # FASE 3: VISUALIZACIÓN
        col_m, col_t = st.columns([2, 1])
        
        with col_m:
            st.markdown("### 🕸️ Mapa de Citación")
            net = Network(height="650px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            net.repulsion(node_distance=200, spring_length=200)
            
            # Generar HTML y mostrarlo
            net_html = net.generate_html()
            components.html(net_html, height=700)

        with col_t:
            st.markdown("### 📄 Tabla de Datos")
            df = pd.DataFrame(data_base)
            st.dataframe(df, use_container_width=True)
            
            st.download_button(
                label="📥 Descargar CSV",
                data=df.to_csv(index=False).encode('utf-8'),
                file_name=f"investigacion_{query.replace(' ','_')}.csv",
                mime="text/csv"
            )
    else:
        st.warning("Escribe algo antes de buscar.")