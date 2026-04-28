import streamlit as st
import requests
import concurrent.futures
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import time
import pandas as pd
import re
import unicodedata

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AcademiGraph Pro | Meta-Intelligence", layout="wide", page_icon="🔗")

# --- UTILIDADES DE NORMALIZACIÓN ---

def normalizar_texto(texto):
    """Limpia el título para mejorar la coincidencia entre diferentes APIs."""
    if not texto: return ""
    # Quitar tildes y caracteres especiales
    texto = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode("utf-8")
    # A minúsculas y quitar puntuación
    texto = re.sub(r'[^\w\s]', '', texto.lower())
    # Quitar espacios extra
    return " ".join(texto.split())

# --- FUNCIÓN DE ENRIQUECIMIENTO DE CITAS (MULTI-API) ---

def enriquecer_citas_pro(articulo):
    if articulo.get("Citas") and articulo["Citas"] > 0:
        return articulo
    
    titulo_norm = normalizar_texto(articulo.get("Título"))
    doi = articulo.get("DOI")
    
    # Intento 1: Semantic Scholar
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={articulo['Título']}&limit=1&fields=citationCount"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            citas = data.get("citationCount") if doi else data.get("data", [{}])[0].get("citationCount", 0)
            if citas: 
                articulo["Citas"] = citas
                return articulo
    except: pass

    # Intento 2: OpenCitations (Solo si hay DOI)
    if doi:
        try:
            res = requests.get(f"https://opencitations.net/index/coci/api/v1/citations/{doi}", timeout=5)
            if res.status_code == 200:
                articulo["Citas"] = len(res.json())
                return articulo
        except: pass
        
    return articulo

# --- 1. MOTORES DE BÚSQUEDA ---

def buscar_federado_global(materia, limite, email, perfil, campo):
    resultados = []
    
    def buscar_oa():
        try:
            params = {"per-page": limite, "mailto": email, "sort": "cited_by_count:desc"}
            if campo == "ORCID": params["filter"] = f"author.orcid:https://orcid.org/{materia}"
            elif campo == "Título": params["filter"] = f"title.search:{materia}"
            elif campo == "Autor (Nombre)": params["filter"] = f"authorships.author.display_name.search:{materia}"
            else: params["search"] = f"{materia} (law OR economics OR business)" if perfil == "Derecho/Economía" else materia

            res = requests.get("https://api.openalex.org/works", params=params, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    resultados.append({
                        "Fuente": "Dimensions (via OA)", "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": item.get("doi", "").replace("https://doi.org/", ""),
                        "Citas": int(item.get("cited_by_count", 0))
                    })
        except: pass

    def buscar_pubmed():
        if perfil == "Derecho/Economía": return
        try:
            tag = "[auid]" if campo == "ORCID" else "[ti]" if campo == "Título" else "[au]" if campo == "Autor (Nombre)" else ""
            res = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", 
                               params={"db": "pubmed", "term": f"{materia}{tag}", "retmax": limite, "retmode": "json"}, timeout=10)
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

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_pubmed)
        executor.submit(buscar_cr)
    return resultados

# --- 2. MOTOR DE RED HÍBRIDO (EL CORAZÓN DEL SISTEMA) ---

@st.cache_data(ttl=3600)
def obtener_red_meta(doi, titulo, limite_red=5):
    refs, cits = [], []
    
    # 1. Intento con Semantic Scholar (Principal)
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            p_id = data.get("paperId") if doi else data.get("data", [{}])[0].get("paperId")
            if p_id:
                r_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/references", params={"limit": limite_red, "fields": "title"}, timeout=10)
                refs = [i['citedPaper']['title'] for i in r_res.json().get('data', []) if i.get('citedPaper')]
                c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", params={"limit": limite_red, "fields": "title"}, timeout=10)
                cits = [i['citingPaper']['title'] for i in c_res.json().get('data', []) if i.get('citingPaper')]
    except: pass

    # 2. Respaldo con OpenCitations (Solo si hay DOI y pocas citas encontradas)
    if doi and len(cits) < 2:
        try:
            # Buscamos quién cita a este DOI
            res_oc = requests.get(f"https://opencitations.net/index/coci/api/v1/citations/{doi}", timeout=10)
            if res_oc.status_code == 200:
                for item in res_oc.json()[:limite_red]:
                    # Obtenemos el título del que cita (requiere otra llamada pequeña)
                    citing_doi = item.get("citing")
                    meta = requests.get(f"https://api.crossref.org/works/{citing_doi}", timeout=5)
                    if meta.status_code == 200:
                        cits.append(meta.json()["message"]["title"][0])
        except: pass

    return list(set(refs)), list(set(cits))

# --- 3. INTERFAZ ---

st.title("🌐 AcademiGraph Pro: Meta-Intelligence")

with st.sidebar:
    st.header("⚙️ Configuración")
    campo_busqueda = st.selectbox("Buscar por:", ["Palabras Clave", "Título", "Autor (Nombre)", "ORCID"])
    perfil = st.selectbox("Perfil Especialidad:", ["General", "Derecho/Economía"])
    n_results = st.slider("Resultados por motor", 5, 25, 10)
    st.divider()
    st.caption("Normalización de títulos y Meta-APIs activadas.")

query = st.text_input(f"Introduce el {campo_busqueda}:")

if st.button("🚀 Lanzar Investigación"):
    if query:
        with st.status("Ejecutando Meta-Búsqueda...", expanded=True) as s:
            data_raw = buscar_federado_global(query, n_results, "investigador@institucion.edu", perfil, campo_busqueda)
            
            s.write("Normalizando y enriqueciendo impacto (Crossref/OpenCitations)...")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                data_base = list(executor.map(enriquecer_citas_pro, data_raw))
            
            grafo = nx.DiGraph()
            progreso = st.progress(0)
            
            for i, art in enumerate(data_base):
                r_list, c_list = obtener_red_meta(art['DOI'], art['Título'])
                grafo.add_node(art['Título'], color='#4CAF50', size=30)
                for r in r_list:
                    grafo.add_node(r, color='#FF5722', size=15)
                    grafo.add_edge(art['Título'], r)
                for c in c_list:
                    grafo.add_node(c, color='#2196F3', size=15)
                    grafo.add_edge(c, art['Título'])
                progreso.progress((i + 1) / len(data_base))
                time.sleep(1.1)

        col_m, col_d = st.columns([2, 1])
        with col_m:
            net = Network(height="750px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            components.html(net.generate_html(), height=800)
        with col_d:
            df = pd.DataFrame(data_base)
            if not df.empty:
                df["Citas"] = pd.to_numeric(df["Citas"], errors='coerce').fillna(0).astype(int)
                st.dataframe(df.sort_values(by="Citas", ascending=False), use_container_width=True)
