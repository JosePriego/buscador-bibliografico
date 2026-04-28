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
    page_title="AcademiGraph Pro | Total Intelligence", 
    layout="wide", 
    page_icon="🌍"
)

# --- ESTILOS ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; font-weight: bold; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #1c83e1; color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- FUNCIÓN DE ENRIQUECIMIENTO (EL SECRETO DE LAS CITAS) ---

def enriquecer_citas(articulo):
    """Consulta Semantic Scholar para obtener el conteo de citas real si no existe."""
    if articulo.get("Citas") and articulo["Citas"] > 0:
        return articulo
    
    try:
        doi = articulo.get("DOI")
        titulo = articulo.get("Título")
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1&fields=citationCount"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if doi:
                articulo["Citas"] = data.get("citationCount", 0)
            else:
                results = data.get("data", [])
                if results:
                    articulo["Citas"] = results[0].get("citationCount", 0)
    except:
        pass
    return articulo

# --- 1. MOTORES DE BÚSQUEDA ---

def buscar_federado_global(materia, limite, email, perfil):
    resultados = []
    query_busqueda = f"{materia} (law OR economics OR business)" if perfil == "Derecho/Economía" else materia

    # MOTOR 1: OPENALEX
    def buscar_oa():
        try:
            res = requests.get("https://api.openalex.org/works", 
                               params={"search": query_busqueda, "per-page": limite, "mailto": email, "sort": "cited_by_count:desc"}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    resultados.append({
                        "Fuente": "Dimensions (via OA)", "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": item.get("doi", "").replace("https://doi.org/", ""),
                        "Citas": int(item.get("cited_by_count", 0))
                    })
        except: pass

    # MOTOR 2: PUBMED
    def buscar_pubmed():
        if perfil == "Derecho/Economía": return
        try:
            base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
            s_res = requests.get(f"{base_url}esearch.fcgi", params={"db": "pubmed", "term": materia, "retmax": limite, "retmode": "json"}, timeout=10)
            ids = s_res.json().get("esearchresult", {}).get("idlist", [])
            if ids:
                f_res = requests.get(f"{base_url}esummary.fcgi", params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"}, timeout=10)
                summaries = f_res.json().get("result", {})
                for uid in ids:
                    if uid == "uids": continue
                    paper = summaries.get(uid, {})
                    eloc = paper.get("elocationid", "")
                    resultados.append({
                        "Fuente": "PubMed", "Título": paper.get("title", "N/A"),
                        "Autor": paper.get("authors", [{}])[0].get("name", "N/A") if paper.get("authors") else "N/A",
                        "DOI": eloc.replace("doi: ", "") if "doi:" in eloc else None,
                        "Citas": 0 # Se enriquecerá después
                    })
        except: pass

    # MOTOR 3: CORE
    def buscar_core():
        try:
            res = requests.get(f"https://api.core.ac.uk/v3/search/works", params={"q": query_busqueda, "limit": limite}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    resultados.append({
                        "Fuente": "CORE", "Título": item.get("title"),
                        "Autor": item.get("authors", [{}])[0].get("name", "N/A") if item.get("authors") else "N/A",
                        "DOI": item.get("doi"), "Citas": 0 # Se enriquecerá después
                    })
        except: pass

    # MOTOR 4: CROSSREF
    def buscar_cr():
        q_cr = f"{materia} RePEc SSRN" if perfil == "Derecho/Economía" else query_busqueda
        try:
            res = requests.get("https://api.crossref.org/works", 
                               params={"query": q_cr, "rows": limite, "mailto": email, "sort": "is-referenced-by-count", "order": "desc"}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    resultados.append({
                        "Fuente": "Crossref", "Título": item.get("title", [""])[0],
                        "Autor": item.get("author", [{}])[0].get("family", "N/A") if item.get("author") else "N/A",
                        "DOI": item.get("DOI"), "Citas": int(item.get("is-referenced-by-count", 0))
                    })
        except: pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_pubmed)
        executor.submit(buscar_core)
        executor.submit(buscar_cr)
        
    return resultados

# --- 2. MOTOR DE RED CON CACHÉ ---

@st.cache_data(ttl=3600)
def obtener_red_cached(doi, titulo, limite_red=5):
    refs, cits = [], []
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res = requests.get(url, timeout=12)
        if res.status_code == 200:
            data = res.json()
            p_id = data.get("paperId") if doi else data.get("data", [{}])[0].get("paperId")
            if p_id:
                r_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/references", params={"limit": limite_red, "fields": "title"}, timeout=10)
                if r_res.status_code == 200:
                    refs = [i['citedPaper']['title'] for i in r_res.json().get('data', []) if i.get('citedPaper')]
                
                c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", params={"limit": limite_red, "fields": "title"}, timeout=10)
                if c_res.status_code == 200:
                    cits = [i['citingPaper']['title'] for i in c_res.json().get('data', []) if i.get('citingPaper')]
    except: pass
    return refs, cits

# --- 3. INTERFAZ STREAMLIT ---

st.title("🌍 AcademiGraph Pro: Global Research Intelligence")

with st.sidebar:
    st.header("⚙️ Configuración")
    perfil = st.selectbox("Perfil de Búsqueda", ["General", "Derecho/Economía"])
    user_email = st.text_input("Email Investigador", "investigador@institucion.edu")
    n_results = st.slider("Resultados por motor", 5, 25, 10)
    st.divider()
    st.info("📊 Ahora los resultados de PubMed y CORE también muestran sus citas reales.")

query = st.text_input("Investigar materia:", placeholder="Ej: Blockchain and Law")

if st.button("🚀 Iniciar Investigación"):
    if query:
        with st.status("Consultando infraestructura científica...", expanded=True) as s:
            # FASE 1: BÚSQUEDA
            data_raw = buscar_federado_global(query, n_results, user_email, perfil)
            data_raw = [d for d in data_raw if d['Título']]
            
            # FASE 2: ENRIQUECIMIENTO DE CITAS (En paralelo)
            s.write("Enriqueciendo datos de impacto de PubMed y CORE...")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                data_base = list(executor.map(enriquecer_citas, data_raw))
            
            # FASE 3: MAPEO DE RED
            s.write("Construyendo mapa de citación bidireccional...")
            grafo = nx.DiGraph()
            progreso = st.progress(0)
            
            for i, art in enumerate(data_base):
                r_list, c_list = obtener_red_cached(art['DOI'], art['Título'])
                grafo.add_node(art['Título'], color='#4CAF50', size=30)
                for r in r_list:
                    grafo.add_node(r, color='#FF5722', size=15)
                    grafo.add_edge(art['Título'], r, color='#FF5722')
                for c in c_list:
                    grafo.add_node(c, color='#2196F3', size=15)
                    grafo.add_edge(c, art['Título'], color='#2196F3')
                
                progreso.progress((i + 1) / len(data_base))
                time.sleep(1.2)

            s.update(label="¡Procesamiento completo!", state="complete")

        # UI Visualización
        col_m, col_d = st.columns([2, 1])
        with col_m:
            st.markdown(f"### 🕸️ Mapa de Impacto Global")
            net = Network(height="750px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            net.toggle_physics(True)
            net.repulsion(node_distance=180)
            components.html(net.generate_html(), height=800)

        with col_d:
            st.markdown("### 📊 Ranking de Resultados")
            df = pd.DataFrame(data_base)
            if not df.empty:
                df["Citas"] = pd.to_numeric(df["Citas"], errors='coerce').fillna(0).astype(int)
                df_sorted = df.sort_values(by="Citas", ascending=False)
                st.dataframe(df_sorted, use_container_width=True)
                st.download_button("📥 Descargar Reporte CSV", df_sorted.to_csv(index=False).encode('utf-8'), "reporte_global.csv")
    else:
        st.warning("Escribe un término para iniciar.")
