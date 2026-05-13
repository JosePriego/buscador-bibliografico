import streamlit as st
import requests
import concurrent.futures
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import pandas as pd
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="AcademiGraph Pro | Scopus Edition", layout="wide", page_icon="🎓")

# Estilo profesional
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background: linear-gradient(90deg, #ffb347, #ffcc33); color: black; font-weight: bold; border: none; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- MOTORES DE BÚSQUEDA ---

class AcademicEngine:
    def __init__(self, email, scopus_key=None):
        self.email = email
        self.scopus_key = scopus_key
        self.headers_scopus = {
            "X-ELS-APIKey": scopus_key,
            "Accept": "application/json"
        }

    def fetch_scopus(self, query, limite, campo):
        if not self.scopus_key: return []
        try:
            # Sintaxis Scopus: TITLE-ABS-KEY para búsqueda general
            q = f"TITLE({query})" if campo == "Título" else f"AUTHOR-NAME({query})" if campo == "Autor" else f"TITLE-ABS-KEY({query})"
            url = "https://api.elsevier.com/content/search/scopus"
            res = requests.get(url, headers=self.headers_scopus, params={"query": q, "count": limite}, timeout=10)
            if res.status_code == 200:
                entries = res.json().get("search-results", {}).get("entry", [])
                return [{
                    "Fuente": "Scopus", "Título": i.get("dc:title"),
                    "Autor": i.get("dc:creator", "N/A"),
                    "DOI": i.get("prism:doi"), "Citas": int(i.get("citedby-count", 0))
                } for i in entries if i.get("dc:title")]
        except: pass
        return []

    def fetch_openalex(self, query, limite):
        try:
            res = requests.get("https://api.openalex.org/works", params={"search": query, "per-page": limite, "mailto": self.email}, timeout=10)
            return [{
                "Fuente": "OpenAlex", "Título": i.get("title"),
                "Autor": i.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                "DOI": i.get("doi", "").replace("https://doi.org/", ""), "Citas": i.get("cited_by_count", 0)
            } for i in res.json().get("results", [])]
        except: return []

# --- ENRIQUECIMIENTO DE RED (Semantic Scholar) ---

@st.cache_data(ttl=3600)
def get_paper_network(doi, titulo, limit=5):
    """Obtiene el conteo real de citas, referencias (rojo) y citas recibidas (azul)."""
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1&fields=citationCount,paperId"
        data = requests.get(url, timeout=8).json()
        paper = data if doi else data.get("data", [{}])[0]
        p_id = paper.get("paperId")
        
        if not p_id: return paper.get("citationCount", 0), [], []
        
        # Referencias y Citas
        r_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/references", params={"limit": limit, "fields": "title"}).json()
        c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", params={"limit": limit, "fields": "title"}).json()
        
        refs = [i['citedPaper']['title'] for i in r_res.get('data', []) if i.get('citedPaper')]
        cits = [i['citingPaper']['title'] for i in c_res.get('data', []) if i.get('citingPaper')]
        return paper.get("citationCount", 0), refs, cits
    except: return 0, [], []

# --- INTERFAZ ---

st.title("🎓 AcademiGraph Pro: Edición Scopus")

with st.sidebar:
    st.header("🔑 Acceso API")
    scopus_key = st.text_input("Scopus API Key", type="password", help="Introduce tu clave de Elsevier")
    user_email = st.text_input("Email (Polite Pool)", "investigador@institucion.edu")
    st.divider()
    n_results = st.slider("Artículos base", 5, 20, 10)
    st.caption("Nota: Scopus suele requerir conexión VPN institucional.")

query = st.text_input("Término de búsqueda académica:", placeholder="Ej: Blockchain in healthcare")

if st.button("🚀 Iniciar Investigación"):
    if not query:
        st.warning("Introduce un término de búsqueda.")
    elif not scopus_key:
        st.error("Se requiere una API Key de Scopus para esta versión.")
    else:
        engine = AcademicEngine(user_email, scopus_key)
        
        with st.status("📡 Consultando bases de datos de alto impacto...", expanded=True) as s:
            # 1. Búsqueda en paralelo
            with concurrent.futures.ThreadPoolExecutor() as executor:
                f_sc = executor.submit(engine.fetch_scopus, query, n_results, "General")
                f_oa = executor.submit(engine.fetch_openalex, query, n_results)
                raw_results = f_sc.result() + f_oa.result()
            
            # Deduplicación
            vistos, data_unicos = set(), []
            for item in raw_results:
                t = item['Título'].lower().strip()
                if t not in vistos:
                    vistos.add(t); data_unicos.append(item)
            
            s.write(f"✅ {len(data_unicos)} artículos encontrados. Generando red genealógica...")
            
            # 2. Construcción del Grafo y Lista Maestra
            G = nx.DiGraph()
            export_list = []
            
            for art in data_unicos:
                citas_reales, refs, cits = get_paper_network(art['DOI'], art['Título'])
                
                # Nodo Principal (Verde)
                G.add_node(art['Título'], color='#4CAF50', size=30, title=f"Fuente: {art['Fuente']} | Citas: {citas_reales}")
                export_list.append({"Título": art['Título'], "Tipo": "PRINCIPAL", "Relación con": "N/A", "Fuente": art['Fuente']})
                
                # Referencias (Rojo)
                for r in refs:
                    G.add_node(r, color='#FF5722', size=15, title="Referencia (Antecedente)")
                    G.add_edge(art['Título'], r, color='#FF5722')
                    export_list.append({"Título": r, "Tipo": "REFERENCIA", "Relación con": art['Título'], "Fuente": "Semantic Scholar"})
                
                # Citas (Azul)
                for c in cits:
                    G.add_node(c, color='#2196F3', size=15, title="Cita (Impacto futuro)")
                    G.add_edge(c, art['Título'], color='#2196F3')
                    export_list.append({"Título": c, "Tipo": "CITA", "Relación con": art['Título'], "Fuente": "Semantic Scholar"})
            
            st.session_state.grafo = G
            st.session_state.export_data = export_list
            s.update(label="¡Mapeo completo!", state="complete")

# --- VISUALIZACIÓN Y DESCARGA ---
if 'grafo' in st.session_state:
    c1, c2 = st.columns([2, 1])
    
    with c1:
        net = Network(height="600px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
        net.from_nx(st.session_state.grafo)
        net.toggle_physics(True)
        components.html(net.generate_html(), height=650)
        
    with c2:
        st.subheader("📊 Exportación Total")
        df = pd.DataFrame(st.session_state.export_data)
        st.write(f"Registros en red: **{len(df)}**")
        
        # El CSV ahora contiene TODA la red (verdes, rojos y azules)
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Descargar Red Completa (CSV)", csv, "red_academica_pro.csv", "text/csv")
        
        st.divider()
        st.dataframe(df, height=400)
