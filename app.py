import streamlit as st
import requests
import concurrent.futures
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import pandas as pd
from typing import List, Dict

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AcademiGraph Pro | Full Suite", layout="wide", page_icon="🎓")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background: linear-gradient(90deg, #2e7bcf, #1c83e1); color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- CLASE DE MOTORES DE BÚSQUEDA ---

class AcademicEngine:
    def __init__(self, email, perfil):
        self.headers = {"User-Agent": f"AcademiGraphPro/2.0 (mailto:{email})"}
        self.email = email
        self.perfil = perfil

    def fetch_openalex(self, query, limite, campo):
        try:
            params = {"per-page": limite, "mailto": self.email, "sort": "cited_by_count:desc"}
            if campo == "ORCID": params["filter"] = f"author.orcid:https://orcid.org/{query}"
            elif campo == "Título": params["filter"] = f"title.search:{query}"
            elif campo == "Autor (Nombre)": params["filter"] = f"authorships.author.display_name.search:{query}"
            else: params["search"] = f"{query} (law OR economics)" if self.perfil == "Derecho/Economía" else query
            
            res = requests.get("https://api.openalex.org/works", params=params, timeout=10)
            return [{
                "Fuente": "OpenAlex", "Título": i.get("title"),
                "Autor": i.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                "DOI": i.get("doi", "").replace("https://doi.org/", "") if i.get("doi") else None,
                "Citas": i.get("cited_by_count", 0)
            } for i in res.json().get("results", [])]
        except: return []

    def fetch_pubmed(self, query, limite, campo):
        if self.perfil == "Derecho/Economía": return [] # PubMed no suele ser relevante aquí
        try:
            tag = "[auid]" if campo == "ORCID" else "[ti]" if campo == "Título" else "[au]" if campo == "Autor (Nombre)" else ""
            res = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", 
                               params={"db": "pubmed", "term": f"{query}{tag}", "retmax": limite, "retmode": "json"}, timeout=10)
            ids = res.json().get("esearchresult", {}).get("idlist", [])
            if not ids: return []
            
            res_sum = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", 
                                   params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"}, timeout=10)
            summaries = res_sum.json().get("result", {})
            results = []
            for uid in ids:
                if uid == "uids": continue
                p = summaries.get(uid, {})
                results.append({
                    "Fuente": "PubMed", "Título": p.get("title", "N/A"),
                    "Autor": p.get("authors", [{}])[0].get("name", "N/A"),
                    "DOI": p.get("elocationid", "").replace("doi: ", "") if "doi:" in p.get("elocationid", "") else None,
                    "Citas": 0 # PubMed no da conteo de citas directo en el summary
                })
            return results
        except: return []

    def fetch_crossref(self, query, limite, campo):
        try:
            params = {"rows": limite, "mailto": self.email, "sort": "is-referenced-by-count", "order": "desc"}
            if campo == "ORCID": params["filter"] = f"orcid:{query}"
            elif campo == "Título": params["query.title"] = query
            elif campo == "Autor (Nombre)": params["query.author"] = query
            else: params["query"] = query
            
            res = requests.get("https://api.crossref.org/works", params=params, timeout=10)
            return [{
                "Fuente": "Crossref", "Título": i.get("title", ["N/A"])[0],
                "Autor": i.get("author", [{}])[0].get("family", "N/A") if i.get("author") else "N/A",
                "DOI": i.get("DOI"), "Citas": i.get("is-referenced-by-count", 0)
            } for i in res.json().get("message", {}).get("items", [])]
        except: return []

    def fetch_core(self, query, limite, campo):
        try:
            q_core = f"authors:({query})" if campo in ["Autor (Nombre)", "ORCID"] else f"title:({query})" if campo == "Título" else query
            res = requests.get(f"https://api.core.ac.uk/v3/search/works", params={"q": q_core, "limit": limite}, timeout=10)
            if res.status_code == 200:
                return [{
                    "Fuente": "CORE", "Título": i.get("title"),
                    "Autor": i.get("authors", [{}])[0].get("name", "N/A") if i.get("authors") else "N/A",
                    "DOI": i.get("doi"), "Citas": 0
                } for i in res.json().get("results", [])]
        except: return []

# --- RED Y ENRIQUECIMIENTO ---

@st.cache_data(ttl=3600)
def enriquecer_y_red(doi, titulo, limit=5):
    """Obtiene conteo de citas real y red de referencias en un solo paso."""
    citas_reales = 0
    refs, cits = [], []
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1&fields=citationCount,paperId"
        res = requests.get(url, timeout=8).json()
        
        data = res if doi else res.get("data", [{}])[0]
        paper_id = data.get("paperId")
        citas_reales = data.get("citationCount", 0)
        
        if paper_id:
            # Obtener Red
            base_url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
            r_data = requests.get(f"{base_url}/references", params={"limit": limit, "fields": "title"}, timeout=5).json()
            c_data = requests.get(f"{base_url}/citations", params={"limit": limit, "fields": "title"}, timeout=5).json()
            refs = [r['citedPaper']['title'] for r in r_data.get('data', []) if r.get('citedPaper')]
            cits = [c['citingPaper']['title'] for c in c_data.get('data', []) if c.get('citingPaper')]
            
    except: pass
    return citas_reales, refs, cits

# --- INTERFAZ ---

st.title("🎓 AcademiGraph Pro: Inteligencia Global")

with st.sidebar:
    st.header("⚙️ Configuración")
    campo_busqueda = st.selectbox("Buscar por:", ["Palabras Clave", "Título", "Autor (Nombre)", "ORCID"])
    perfil = st.selectbox("Perfil de Especialidad:", ["General", "Derecho/Economía"])
    user_email = st.text_input("Email (Polite Pool)", "investigador@institucion.edu")
    n_results = st.slider("Resultados por motor", 5, 25, 10)

query = st.text_input(f"Introduce el {campo_busqueda}:")

if st.button("🚀 Lanzar Investigación"):
    if query:
        engine = AcademicEngine(user_email, perfil)
        
        with st.status("📡 Consultando infraestructura científica global (4 motores)...", expanded=True) as status:
            # 1. BÚSQUEDA FEDERADA
            with concurrent.futures.ThreadPoolExecutor() as executor:
                f_oa = executor.submit(engine.fetch_openalex, query, n_results, campo_busqueda)
                f_pm = executor.submit(engine.fetch_pubmed, query, n_results, campo_busqueda)
                f_cr = executor.submit(engine.fetch_crossref, query, n_results, campo_busqueda)
                f_co = executor.submit(engine.fetch_core, query, n_results, campo_busqueda)
                
                raw_data = f_oa.result() + f_pm.result() + f_cr.result() + f_co.result()

            # Deduplicación por Título
            vistos = set()
            data_unicos = []
            for d in raw_data:
                t = d['Título'].lower().strip()
                if t not in vistos and d['Título']:
                    vistos.add(t)
                    data_unicos.append(d)
            
            status.write(f"✅ {len(data_unicos)} artículos únicos localizados.")

            # 2. ENRIQUECIMIENTO Y GRAFO
            status.write("🕸️ Sincronizando métricas de impacto y red de citas...")
            G = nx.DiGraph()
            
            # Procesamos en paralelo para no morir esperando
            def procesar_completo(art):
                citas, refs, cits = enriquecer_y_red(art['DOI'], art['Título'])
                art['Citas'] = max(art['Citas'], citas)
                return art, refs, cits

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(procesar_completo, a) for a in data_unicos]
                for future in concurrent.futures.as_completed(futures):
                    art, refs, cits = future.result()
                    
                    G.add_node(art['Título'], color='#4CAF50', size=25, title=f"Fuente: {art['Fuente']}")
                    for r in refs:
                        G.add_node(r, color='#FF5722', size=12, title="Referencia")
                        G.add_edge(art['Título'], r, color='#FF5722')
                    for c in cits:
                        G.add_node(c, color='#2196F3', size=12, title="Cita")
                        G.add_edge(c, art['Título'], color='#2196F3')

            st.session_state.data = data_unicos
            st.session_state.grafo = G
            status.update(label="¡Análisis masivo completado!", state="complete")

# --- RENDER ---
if 'grafo' in st.session_state:
    col1, col2 = st.columns([2, 1])
    with col1:
        net = Network(height="650px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
        net.from_nx(st.session_state.grafo)
        net.toggle_physics(True)
        components.html(net.generate_html(), height=700)
    
    with col2:
        st.subheader("📊 Ranking")
        df = pd.DataFrame(st.session_state.data).sort_values(by="Citas", ascending=False)
        st.dataframe(df[["Título", "Citas", "Fuente"]], hide_index=True)
        st.download_button("📥 Descargar CSV", df.to_csv(index=False).encode('utf-8'), "data.csv")
