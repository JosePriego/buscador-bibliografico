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
    page_title="AcademiGraph Pro | GitHub Edition", 
    layout="wide", 
    page_icon="🎓"
)

# Estilos visuales personalizados
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background: linear-gradient(90deg, #ffb347, #ffcc33); color: black; font-weight: bold; border: none; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- VALIDACIÓN DE SECRETOS (VÍA PROFESIONAL) ---
# Borra el try/except anterior y pon esto:
if "SCOPUS_KEY" not in st.secrets:
    st.write("### 🔍 Diagnóstico de Secretos")
    st.write("Streamlit no encuentra 'SCOPUS_KEY', pero sí encuentra estas llaves:", list(st.secrets.keys()))
    st.stop()
else:
    SCOPUS_API_KEY = st.secrets["SCOPUS_KEY"]

# --- CLASE DE MOTORES DE BÚSQUEDA ---

class AcademicEngine:
    def __init__(self, email, scopus_key):
        self.email = email
        self.scopus_key = scopus_key
        self.headers_scopus = {
            "X-ELS-APIKey": scopus_key,
            "Accept": "application/json"
        }

    def fetch_scopus(self, query, limite):
        """Busca directamente en Scopus usando la API Key segura."""
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
        """Motor complementario OpenAlex para mayor cobertura."""
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

# --- MOTOR DE RED (SEMANTIC SCHOLAR) ---

@st.cache_data(ttl=3600)
def expandir_red_bibliografica(doi, titulo, limit=5):
    """Mapea las conexiones (referencias y citas) de cada artículo[cite: 1]."""
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1&fields=citationCount,paperId"
        res = requests.get(url, timeout=8).json()
        paper = res if doi else res.get("data", [{}])[0]
        p_id = paper.get("paperId")
        
        if not p_id: return paper.get("citationCount", 0), [], []
        
        base_url = f"https://api.semanticscholar.org/graph/v1/paper/{p_id}"
        # Referencias (Rojo) y Citas (Azul)
        r_data = requests.get(f"{base_url}/references", params={"limit": limit, "fields": "title"}).json()
        c_data = requests.get(f"{base_url}/citations", params={"limit": limit, "fields": "title"}).json()
        
        refs = [i['citedPaper']['title'] for i in r_data.get('data', []) if i.get('citedPaper')]
        cits = [i['citingPaper']['title'] for i in c_data.get('data', []) if i.get('citingPaper')]
        return paper.get("citationCount", 0), refs, cits
    except: return 0, [], []

# --- INTERFAZ PRINCIPAL ---

st.title("🎓 AcademiGraph Pro")
st.markdown("### Inteligencia Bibliométrica con Scopus y Exportación Excel")

with st.sidebar:
    st.header("⚙️ Configuración")
    user_email = st.text_input("Email (Polite Pool)", "investigador@institucion.edu")
    n_results = st.slider("Resultados base por motor", 5, 30, 12)
    st.divider()
    st.success("✅ Conectado a Scopus vía Secretos")

query = st.text_input("Introduce el tema de investigación:", placeholder="Ej: Artificial Intelligence in Education")

if st.button("🚀 Iniciar Investigación"):
    if query:
        engine = AcademicEngine(user_email, SCOPUS_API_KEY)
        
        with st.status("🔍 Consultando bases de datos globales...", expanded=True) as status:
            # 1. Búsqueda concurrente
            with concurrent.futures.ThreadPoolExecutor() as executor:
                f_sc = executor.submit(engine.fetch_scopus, query, n_results)
                f_oa = executor.submit(engine.fetch_openalex, query, n_results)
                raw_data = f_sc.result() + f_oa.result()
            
            # 2. Deduplicación
            vistos, unicos = set(), []
            for item in raw_data:
                t = item['Título'].lower().strip()
                if t not in vistos:
                    vistos.add(t); unicos.append(item)
            
            status.write(f"✅ Se encontraron {len(unicos)} artículos base. Construyendo red genealógica...")

            # 3. Mapeo de Grafo y Datos de Exportación
            G = nx.DiGraph()
            export_data = []
            
            for art in unicos:
                c_val, refs, cits = expandir_red_bibliografica(art['DOI'], art['Título'])
                
                # Nodo Principal
                G.add_node(art['Título'], color='#4CAF50', size=30, title=f"Origen: {art['Fuente']}")
                export_data.append({"Título": art['Título'], "Relación": "PRINCIPAL", "Fuente": art['Fuente'], "Vínculo": "Búsqueda Directa"})
                
                # Nodos de Referencia (Pasado)
                for r in refs:
                    G.add_node(r, color='#FF5722', size=15)
                    G.add_edge(art['Título'], r, color='#FF5722')
                    export_data.append({"Título": r, "Relación": "REFERENCIA", "Fuente": "Semantic Scholar", "Vínculo": art['Título']})
                
                # Nodos de Cita (Futuro)
                for c in cits:
                    G.add_node(c, color='#2196F3', size=15)
                    G.add_edge(c, art['Título'], color='#2196F3')
                    export_data.append({"Título": c, "Relación": "CITA", "Fuente": "Semantic Scholar", "Vínculo": art['Título']})
            
            st.session_state.grafo = G
            st.session_state.data_export = export_data
            status.update(label="¡Análisis completado!", state="complete")

# --- RENDERIZADO DE RESULTADOS ---

if 'grafo' in st.session_state:
    col_map, col_table = st.columns([2, 1])
    
    with col_map:
        st.subheader("🌐 Visualización de la Red")
        net = Network(height="650px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
        net.from_nx(st.session_state.grafo)
        net.toggle_physics(True)
        components.html(net.generate_html(), height=700)
        
    with col_table:
        st.subheader("📊 Reporte de Datos")
        df = pd.DataFrame(st.session_state.data_export)
        
        # Exportación a Excel nativo[cite: 1]
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Red_Academica')
        
        st.download_button(
            label="📥 Descargar Base de Datos (.xlsx)",
            data=buffer.getvalue(),
            file_name=f"Red_{query.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.divider()
        st.dataframe(df, height=500)
