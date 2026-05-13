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
    page_title="AcademiGraph Pro | Excel Quotes Edition", 
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

# --- CARGA DE SECRETOS ---
try:
    SCOPUS_API_KEY = st.secrets["SCOPUS_KEY"][cite: 1]
except Exception:
    st.error("❌ Error: No se encontró 'SCOPUS_KEY' en los Secretos de Streamlit.")
    st.stop()

# --- CLASE DE MOTORES ---

class AcademicEngine:
    def __init__(self, email, scopus_key):
        self.email = email
        self.scopus_key = scopus_key
        self.headers_scopus = {"X-ELS-APIKey": scopus_key, "Accept": "application/json"}

    def fetch_scopus(self, query, limite):
        try:
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
            return [{
                "Fuente": "OpenAlex", 
                "Título": i.get("title"),
                "Autor": i.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                "DOI": i.get("doi", "").replace("https://doi.org/", ""), 
                "Citas": i.get("cited_by_count", 0)
            } for i in res.json().get("results", [])]
        except: return []

# --- MOTOR DE RED ---

@st.cache_data(ttl=3600)
def expandir_red(doi, titulo, limit=5):
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1&fields=citationCount,paperId"
        res = requests.get(url, timeout=8).json()
        paper = res if doi else res.get("data", [{}])[0]
        p_id = paper.get("paperId")
        cit_count = paper.get("citationCount", 0)
        
        if not p_id: return cit_count, [], []
        
        base_url = f"https://api.semanticscholar.org/graph/v1/paper/{p_id}"
        r_data = requests.get(f"{base_url}/references", params={"limit": limit, "fields": "title"}).json()
        c_data = requests.get(f"{base_url}/citations", params={"limit": limit, "fields": "title"}).json()
        
        refs = [i['citedPaper']['title'] for i in r_data.get('data', []) if i.get('citedPaper')]
        cits = [i['citingPaper']['title'] for i in c_data.get('data', []) if i.get('citingPaper')]
        return cit_count, refs, cits
    except: return 0, [], []

# --- INTERFAZ ---

st.title("🎓 AcademiGraph Pro")
st.markdown("### Análisis Bibliométrico con Exportación de Citas")

with st.sidebar:
    st.header("⚙️ Configuración")
    user_email = st.text_input("Email", "investigador@institucion.edu")
    n_results = st.slider("Resultados base", 5, 25, 10)
    st.success("🔑 Scopus Key cargada")

query = st.text_input("Tema a investigar:")

if st.button("🚀 Lanzar Análisis"):
    if query:
        engine = AcademicEngine(user_email, SCOPUS_API_KEY)
        
        with st.status("🔍 Consultando bases de datos...", expanded=True) as status:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                f_sc = executor.submit(engine.fetch_scopus, query, n_results)
                f_oa = executor.submit(engine.fetch_openalex, query, n_results)
                raw_data = f_sc.result() + f_oa.result()
            
            vistos, unicos = set(), []
            for item in raw_data:
                t = item['Título'].lower().strip()
                if t not in vistos:
                    vistos.add(t); unicos.append(item)
            
            status.write(f"✅ Artículos base listos. Extrayendo red de citas...")

            G = nx.DiGraph()
            final_data = []
            
            for art in unicos:
                # Obtenemos las citas reales y la red de Semantic Scholar
                citas_reales, refs, cits = expandir_red(art['DOI'], art['Título'])
                
                # Nodo Principal (Verde)
                G.add_node(art['Título'], color='#4CAF50', size=30)
                final_data.append({
                    "Título": art['Título'], 
                    "Citas": citas_reales, # AHORA SÍ SE INCLUYE
                    "Relación": "PRINCIPAL", 
                    "Fuente": art['Fuente'], 
                    "Vínculo": "Búsqueda Directa"
                })
                
                # Referencias (Rojo)[cite: 1]
                for r in refs:
                    G.add_node(r, color='#FF5722', size=15)
                    G.add_edge(art['Título'], r, color='#FF5722')
                    final_data.append({
                        "Título": r, 
                        "Citas": "N/A (Ref)", 
                        "Relación": "REFERENCIA", 
                        "Fuente": "Semantic Scholar", 
                        "Vínculo": art['Título']
                    })
                
                # Citas Recibidas (Azul)[cite: 1]
                for c in cits:
                    G.add_node(c, color='#2196F3', size=15)
                    G.add_edge(c, art['Título'], color='#2196F3')
                    final_data.append({
                        "Título": c, 
                        "Citas": "N/A (Cita)", 
                        "Relación": "CITA", 
                        "Fuente": "Semantic Scholar", 
                        "Vínculo": art['Título']
                    })
            
            st.session_state.grafo = G
            st.session_state.data_export = final_data
            status.update(label="Análisis completado.", state="complete")

# --- RENDERIZADO ---

if 'grafo' in st.session_state:
    c1, c2 = st.columns([2, 1])
    
    with c1:
        net = Network(height="600px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
        net.from_nx(st.session_state.grafo)
        net.toggle_physics(True)
        components.html(net.generate_html(), height=650)
        
    with c2:
        st.subheader("📊 Exportar a Excel")
        df = pd.DataFrame(st.session_state.data_export)
        
        # Generar Excel con columna de Citas[cite: 1]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Resultados_Bibliometricos')
        
        st.download_button(
            label="📥 Descargar Excel (.xlsx)",
            data=output.getvalue(),
            file_name=f"Analisis_{query.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.dataframe(df, height=500)
