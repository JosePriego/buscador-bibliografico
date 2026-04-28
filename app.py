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
    page_title="AcademiGraph Pro | High-Volume Search", 
    layout="wide", 
    page_icon="🚀"
)

# --- ESTILOS ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; font-weight: bold; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #1c83e1; color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. MOTORES DE BÚSQUEDA FEDERADOS ---

def buscar_federado_total(materia, limite, email, perfil):
    resultados = []
    
    def buscar_oa():
        try:
            res = requests.get("https://api.openalex.org/works", 
                               params={"search": materia, "per-page": limite, "mailto": email, "sort": "cited_by_count:desc"}, timeout=20)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    doi_url = item.get("doi")
                    resultados.append({
                        "Fuente": "OpenAlex/Dimensions", "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": doi_url.replace("https://doi.org/", "") if doi_url else None,
                        "Citas": int(item.get("cited_by_count", 0))
                    })
        except: pass

    def buscar_core():
        try:
            res = requests.get(f"https://api.core.ac.uk/v3/search/works", params={"q": materia, "limit": limite}, timeout=20)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    resultados.append({
                        "Fuente": "CORE", "Título": item.get("title"),
                        "Autor": item.get("authors", [{}])[0].get("name", "N/A") if item.get("authors") else "N/A",
                        "DOI": item.get("doi"), "Citas": 0
                    })
        except: pass

    def buscar_cr():
        try:
            res = requests.get("https://api.crossref.org/works", 
                               params={"query": materia, "rows": limite, "mailto": email, "sort": "is-referenced-by-count", "order": "desc"}, timeout=20)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    resultados.append({
                        "Fuente": "Crossref", "Título": item.get("title", [""])[0],
                        "Autor": item.get("author", [{}])[0].get("family", "N/A") if item.get("author") else "N/A",
                        "DOI": item.get("DOI"), "Citas": int(item.get("is-referenced-by-count", 0))
                    })
        except: pass

    def buscar_uco():
        try:
            url = "https://mezquita.uco.es/primaws/rest/pub/pnxs"
            params = {"q": f"any,contains,{materia}", "limit": limite, "vid": "34CBUA_UCO:VU1", "tab": "Everything", "scope": "MyInst_and_CI", "inst": "34CBUA_UCO"}
            res = requests.get(url, params=params, timeout=20)
            if res.status_code == 200:
                for item in res.json().get("docs", []):
                    pnx = item.get("pnx", {})
                    disp = pnx.get("display", {})
                    resultados.append({
                        "Fuente": "UCO", "Título": disp.get("title", [""])[0],
                        "Autor": disp.get("creator", ["N/A"])[0], 
                        "DOI": pnx.get("addata", {}).get("doi", [None])[0], "Citas": 0
                    })
        except: pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_core)
        executor.submit(buscar_cr)
        executor.submit(buscar_uco)
        
    return resultados

# --- 2. MOTOR DE RED CON CACHÉ ---

@st.cache_data(ttl=3600) # Caché de 1 hora para no repetir peticiones idénticas
def obtener_red_cached(doi, titulo, limite_red=5):
    refs, cits = [], []
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            data = res.json()
            p_id = data.get("paperId") if doi else data.get("data", [{}])[0].get("paperId")
            if p_id:
                r_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/references", params={"limit": limite_red, "fields": "title"}, timeout=15)
                if r_res.status_code == 200:
                    refs = [i['citedPaper']['title'] for i in r_res.json().get('data', []) if i.get('citedPaper')]
                
                c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", params={"limit": limite_red, "fields": "title"}, timeout=15)
                if c_res.status_code == 200:
                    cits = [i['citingPaper']['title'] for i in c_res.json().get('data', []) if i.get('citingPaper')]
    except: pass
    return refs, cits

# --- 3. INTERFAZ ---

st.title("🚀 AcademiGraph Pro: High-Volume Edition")

with st.sidebar:
    st.header("⚙️ Control de Volumen")
    perfil = st.selectbox("Perfil", ["General", "Derecho/Economía"])
    # Aumentamos el límite a 25 por motor para llegar a 100+ en total
    n_results = st.slider("Resultados por motor", 5, 25, 15)
    st.divider()
    st.warning("Nota: Buscar 100 resultados puede tardar hasta 3 minutos debido a los límites de las APIs.")

query = st.text_input("Investigar materia:", placeholder="Ej: Energías renovables")

if st.button("🚀 Iniciar Gran Búsqueda"):
    if query:
        with st.status("Fase 1: Recolectando artículos de impacto...", expanded=True) as s:
            data_base = buscar_federado_total(query, n_results, "investigador@uco.es", perfil)
            s.write(f"✅ Se han localizado {len(data_base)} artículos base.")
            
            s.write("Fase 2: Mapeando conexiones (esto puede tardar)...")
            grafo = nx.DiGraph()
            progreso = st.progress(0)
            
            for i, art in enumerate(data_base):
                # Usamos la versión con caché para acelerar
                r_list, c_list = obtener_red_cached(art['DOI'], art['Título'], limite_red=5)
                
                grafo.add_node(art['Título'], color='#4CAF50', size=30)
                for r in r_list:
                    grafo.add_node(r, color='#FF5722', size=15)
                    grafo.add_edge(art['Título'], r, color='#FF5722')
                for c in c_list:
                    grafo.add_node(c, color='#2196F3', size=15)
                    grafo.add_edge(c, art['Título'], color='#2196F3')
                
                progreso.progress((i + 1) / len(data_base))
                # Pausa de seguridad para evitar bloqueos de IP
                time.sleep(1.2)

            s.update(label="¡Procesamiento masivo completado!", state="complete")

        # Visualización optimizada
        col_m, col_d = st.columns([2, 1])
        with col_m:
            st.markdown(f"### 🕸️ Mapa de Citación ({len(grafo.nodes)} nodos)")
            net = Network(height="750px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            # Desactivamos la física compleja inicial para mejorar el rendimiento en redes grandes
            net.toggle_physics(True)
            net.repulsion(node_distance=150, spring_length=150)
            components.html(net.generate_html(), height=800)

        with col_d:
            st.markdown("### 📊 Datos Ordenados")
            df = pd.DataFrame(data_base)
            if not df.empty:
                df["Citas"] = pd.to_numeric(df["Citas"], errors='coerce').fillna(0).astype(int)
                df_sorted = df.sort_values(by="Citas", ascending=False)
                st.dataframe(df_sorted, use_container_width=True)
                st.download_button("📥 Descargar CSV", df_sorted.to_csv(index=False).encode('utf-8'), "big_search.csv")
    else:
        st.warning("Introduce un término.")
