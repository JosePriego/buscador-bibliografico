import streamlit as st
import requests
import concurrent.futures
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import pandas as pd
import io

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="AcademiGraph Pro | Scopus & Excel Edition", 
    layout="wide", 
    page_icon="🎓"
)

# Estilos visuales
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background: linear-gradient(90deg, #ffb347, #ffcc33); color: black; font-weight: bold; border: none; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- CLASE DE MOTORES DE BÚSQUEDA ---

class AcademicEngine:
    def __init__(self, email, scopus_key=None):
        self.email = email
        self.scopus_key = scopus_key
        self.headers_scopus = {
            "X-ELS-APIKey": scopus_key,
            "Accept": "application/json"
        }

    def fetch_scopus(self, query, limite):
        if not self.scopus_key: return []
        try:
            # Búsqueda general en Scopus (Título, Resumen, Palabras clave)
            url = "https://api.elsevier.com/content/search/scopus"
            params = {"query": f"TITLE-ABS-KEY({query})", "count": limite}
            res = requests.get(url, headers=self.headers_scopus, params=params, timeout=10)
            if res.status_code == 200:
                entries = res.json().get("search-results", {}).get("entry", [])
                return [{
                    "Fuente": "Scopus", 
                    "Título": i.get("dc:title"),
                    "Autor": i.get("dc:creator", "N/A"),
                    "DOI": i.get("prism:doi"), 
                    "Citas": int(i.get("citedby-count", 0))
                } for i in entries if i.get("dc:title")]
        except: pass
        return []

    def fetch_openalex(self, query, limite):
        try:
            url = "https://api.openalex.org/works"
            params = {"search": query, "per-page": limite, "mailto": self.email}
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                return [{
                    "Fuente": "OpenAlex", 
                    "Título": i.get("title"),
                    "Autor": i.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                    "DOI": i.get("doi", "").replace("https://doi.org/", ""), 
                    "Citas": i.get("cited_by_count", 0)
                } for i in res.json().get("results", [])]
        except: return []

# --- FUNCIÓN DE RED (SEMANTIC SCHOLAR) ---

@st.cache_data(ttl=3600)
def expandir_red(doi, titulo, limit=5):
    """Utiliza Semantic Scholar para obtener el ADN del artículo (Referencias y Citas)."""
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1&fields=citationCount,paperId"
        res = requests.get(url, timeout=8).json()
        paper = res if doi else res.get("data", [{}])[0]
        p_id = paper.get("paperId")
        
        if not p_id: return paper.get("citationCount", 0), [], []
        
        # Consultar Referencias (Rojo) y Citas (Azul)
        base = f"https://api.semanticscholar.org/graph/v1/paper/{p_id}"
        r_data = requests.get(f"{base}/references", params={"limit": limit, "fields": "title"}).json()
        c_data = requests.get(f"{base}/citations", params={"limit": limit, "fields": "title"}).json()
        
        refs = [i['citedPaper']['title'] for i in r_data.get('data', []) if i.get('citedPaper')]
        cits = [i['citingPaper']['title'] for i in c_data.get('data', []) if i.get('citingPaper')]
        return paper.get("citationCount", 0), refs, cits
    except: return 0, [], []

# --- INTERFAZ DE USUARIO ---

st.title("🎓 AcademiGraph Pro")
st.subheader("Inteligencia Bibliométrica con Scopus y Exportación Excel")

with st.sidebar:
    st.header("🔑 Configuración")
    scopus_api_key = st.text_input("Scopus API Key", type="password")
    user_email = st.text_input("Email de contacto", "investigador@institucion.edu")
    n_results = st.slider("Resultados base por motor", 5, 25, 10)
    st.info("El sistema usará Scopus para la búsqueda y Semantic Scholar para mapear la red.")

query = st.text_input("Introduce tu tema de investigación:")

if st.button("🚀 Lanzar Investigación"):
    if not query or not scopus_api_key:
        st.error("Por favor, introduce el término de búsqueda y tu API Key de Scopus.")
    else:
        engine = AcademicEngine(user_email, scopus_api_key)
        
        with st.status("🕵️ Investigando en Scopus y OpenAlex...", expanded=True) as status:
            # 1. Búsqueda paralela
            with concurrent.futures.ThreadPoolExecutor() as executor:
                f_sc = executor.submit(engine.fetch_scopus, query, n_results)
                f_oa = executor.submit(engine.fetch_openalex, query, n_results)
                raw_results = f_sc.result() + f_oa.result()
            
            # 2. Deduplicación por título
            vistos, unicos = set(), []
            for item in raw_results:
                t = item['Título'].lower().strip()
                if t not in vistos:
                    vistos.add(t); unicos.append(item)
            
            status.write(f"✅ {len(unicos)} artículos base encontrados. Mapeando conexiones...")

            # 3. Construcción de Red y Datos
            G = nx.DiGraph()
            final_data = []
            
            for art in unicos:
                citas_val, refs, cits = expandir_red(art['DOI'], art['Título'])
                
                # Nodo Principal (Verde)
                G.add_node(art['Título'], color='#4CAF50', size=30, title=f"Fuente: {art['Fuente']}")
                final_data.append({"Título": art['Título'], "Relación": "PRINCIPAL", "Fuente": art['Fuente'], "Conectado a": "N/A"})
                
                # Antecedentes (Rojo)
                for r in refs:
                    G.add_node(r, color='#FF5722', size=15)
                    G.add_edge(art['Título'], r, color='#FF5722')
                    final_data.append({"Título": r, "Relación": "REFERENCIA (Pasado)", "Fuente": "Semantic Scholar", "Conectado a": art['Título']})
                
                # Impacto (Azul)
                for c in cits:
                    G.add_node(c, color='#2196F3', size=15)
                    G.add_edge(c, art['Título'], color='#2196F3')
                    final_data.append({"Título": c, "Relación": "CITA (Futuro)", "Fuente": "Semantic Scholar", "Conectado a": art['Título']})
            
            st.session_state.grafo = G
            st.session_state.data_export = final_data
            status.update(label="¡Investigación completada!", state="complete")

# --- RENDERIZADO DE RESULTADOS ---

if 'grafo' in st.session_state:
    col_graph, col_stats = st.columns([2, 1])
    
    with col_graph:
        st.markdown("### 🌐 Mapa de Relaciones Académicas")
        net = Network(height="600px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
        net.from_nx(st.session_state.grafo)
        net.toggle_physics(True)
        components.html(net.generate_html(), height=650)
        
    with col_stats:
        st.markdown("### 📥 Exportar Resultados")
        df = pd.DataFrame(st.session_state.data_export)
        
        # Conversión a Excel en memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Red_Academica')
        
        st.download_button(
            label="📊 Descargar Red Completa (Excel)",
            data=output.getvalue(),
            file_name=f"Investigacion_{query.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.divider()
        st.write("**Vista previa de los datos:**")
        st.dataframe(df, height=400)
