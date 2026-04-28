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
    page_title="AcademiGraph Pro | Recovery Edition", 
    layout="wide", 
    page_icon="🎓"
)

# --- ESTILOS VISUALES ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; font-weight: bold; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #1c83e1; color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- FUNCIÓN DE ENRIQUECIMIENTO DE CITAS (VERSIÓN ORIGINAL) ---

def enriquecer_citas(articulo):
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
    except: pass
    return articulo

# --- 1. MOTORES DE BÚSQUEDA (VERSIÓN RECUPERADA) ---

def buscar_federado_global(materia, limite, email, perfil, campo):
    resultados = []
    
    # MOTOR 1: OPENALEX
    def buscar_oa():
        try:
            params = {"per-page": limite, "mailto": email, "sort": "cited_by_count:desc"}
            if campo == "ORCID": params["filter"] = f"author.orcid:https://orcid.org/{materia}"
            elif campo == "Título": params["filter"] = f"title.search:{materia}"
            elif campo == "Autor (Nombre)": params["filter"] = f"authorships.author.display_name.search:{materia}"
            else: 
                params["search"] = f"{materia} (law OR economics OR business)" if perfil == "Derecho/Economía" else materia

            res = requests.get("https://api.openalex.org/works", params=params, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    doi_url = item.get("doi")
                    resultados.append({
                        "Fuente": "Dimensions (via OA)", "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": doi_url.replace("https://doi.org/", "") if doi_url else None,
                        "Citas": int(item.get("cited_by_count", 0))
                    })
        except: pass

    # MOTOR 2: PUBMED
    def buscar_pubmed():
        if perfil == "Derecho/Economía": return
        try:
            tag = "[auid]" if campo == "ORCID" else "[ti]" if campo == "Título" else "[au]" if campo == "Autor (Nombre)" else ""
            q_pubmed = f"{materia}{tag}"
            res = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", 
                               params={"db": "pubmed", "term": q_pubmed, "retmax": limite, "retmode": "json"}, timeout=10)
            ids = res.json().get("esearchresult", {}).get("idlist", [])
            if ids:
                res_sum = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"}, timeout=10)
                summaries = res_sum.json().get("result", {})
                for uid in ids:
                    if uid == "uids": continue
                    paper = summaries.get(uid, {})
                    resultados.append({
                        "Fuente": "PubMed", "Título": paper.get("title", "N/A"),
                        "Autor": paper.get("authors", [{}])[0].get("name", "N/A") if paper.get("authors") else "N/A",
                        "DOI": paper.get("elocationid", "").replace("doi: ", "") if "doi:" in paper.get("elocationid", "") else None,
                        "Citas": 0
                    })
        except: pass

    # MOTOR 3: CROSSREF
    def buscar_cr():
        try:
            params = {"rows": limite, "mailto": email, "sort": "is-referenced-by-count", "order": "desc"}
            if campo == "ORCID": params["filter"] = f"orcid:{materia}"
            elif campo == "Título": params["query.title"] = materia
            elif campo == "Autor (Nombre)": params["query.author"] = materia
            else: params["query"] = materia

            res = requests.get("https://api.crossref.org/works", params=params, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    resultados.append({
                        "Fuente": "Crossref", "Título": item.get("title", [""])[0],
                        "Autor": item.get("author", [{}])[0].get("family", "N/A") if item.get("author") else "N/A",
                        "DOI": item.get("DOI"), "Citas": int(item.get("is-referenced-by-count", 0))
                    })
        except: pass

    # MOTOR 4: CORE
    def buscar_core():
        try:
            q_core = f"authors:({materia})" if campo in ["Autor (Nombre)", "ORCID"] else f"title:({materia})" if campo == "Título" else materia
            res = requests.get(f"https://api.core.ac.uk/v3/search/works", params={"q": q_core, "limit": limite}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    resultados.append({
                        "Fuente": "CORE", "Título": item.get("title"),
                        "Autor": item.get("authors", [{}])[0].get("name", "N/A") if item.get("authors") else "N/A",
                        "DOI": item.get("doi"), "Citas": 0
                    })
        except: pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_pubmed)
        executor.submit(buscar_cr)
        executor.submit(buscar_core)
    return resultados

# --- 2. MOTOR DE RED (ESTABLE) ---

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
                refs = [i['citedPaper']['title'] for i in r_res.json().get('data', []) if i.get('citedPaper')]
                c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", params={"limit": limite_red, "fields": "title"}, timeout=10)
                cits = [i['citingPaper']['title'] for i in c_res.json().get('data', []) if i.get('citingPaper')]
    except: pass
    return refs, cits

# --- 3. INTERFAZ ---

st.title("🎓 AcademiGraph Pro: Recuperación Total")

with st.sidebar:
    st.header("⚙️ Filtros")
    campo_busqueda = st.selectbox("Buscar por:", ["Palabras Clave", "Título", "Autor (Nombre)", "ORCID"])
    perfil = st.selectbox("Perfil de Especialidad:", ["General", "Derecho/Economía"])
    user_email = st.text_input("Email (Polite Pool)", "investigador@institucion.edu")
    n_results = st.slider("Resultados por motor", 5, 25, 15)
    st.divider()
    st.info("💡 Hemos vuelto a la versión de búsqueda amplia para asegurar el máximo de resultados.")

query = st.text_input(f"Introduce el {campo_busqueda}:")

if st.button("🚀 Iniciar Gran Búsqueda"):
    if query:
        with st.status("Consultando repositorios globales...", expanded=True) as s:
            # FASE 1: BÚSQUEDA AMPLIA
            data_raw = buscar_federado_global(query, n_results, user_email, perfil, campo_busqueda)
            data_raw = [d for d in data_raw if d['Título']]
            
            # FASE 2: ENRIQUECIMIENTO (Sin filtros restrictivos)
            s.write("Sincronizando métricas de impacto...")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                data_base = list(executor.map(enriquecer_citas, data_raw))
            
            # FASE 3: RED
            s.write("Mapeando conexiones bibliométricas...")
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
                time.sleep(1.1)
            s.update(label="¡Procesamiento completo!", state="complete")

        # UI Visualización
        col_m, col_d = st.columns([2, 1])
        with col_m:
            net = Network(height="750px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            net.toggle_physics(True)
            net.repulsion(node_distance=180)
            components.html(net.generate_html(), height=800)

        with col_d:
            st.markdown("### 📊 Datos Recuperados")
            df = pd.DataFrame(data_base)
            if not df.empty:
                df["Citas"] = pd.to_numeric(df["Citas"], errors='coerce').fillna(0).astype(int)
                df_sorted = df.sort_values(by="Citas", ascending=False)
                st.dataframe(df_sorted, use_container_width=True)
                st.download_button("📥 Descargar Reporte CSV", df_sorted.to_csv(index=False).encode('utf-8'), "reporte_total.csv")
    else:
        st.warning("Introduce un término de búsqueda.")
