import streamlit as st
import requests
import concurrent.futures
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import pandas as pd

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="AcademiGraph Pro | Data Export", layout="wide", page_icon="🎓")

# --- MOTORES DE BÚSQUEDA (Simplificado para brevedad, igual al anterior) ---
class AcademicEngine:
    def __init__(self, email, perfil):
        self.email = email
        self.perfil = perfil

    def fetch_all(self, query, limite, campo):
        # Aquí irían las funciones fetch_openalex, fetch_pubmed, etc. 
        # (Se asume la lógica previa de búsqueda federada)
        return [] 

# --- FUNCIÓN CLAVE: OBTENER RED Y ESTRUCTURAR DATOS ---
@st.cache_data(ttl=3600)
def obtener_metadatos_completos(doi, titulo, limit=5):
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1&fields=citationCount,paperId"
        res = requests.get(url, timeout=8).json()
        data = res if doi else res.get("data", [{}])[0]
        paper_id = data.get("paperId")
        
        refs, cits = [], []
        if paper_id:
            base_url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
            r_data = requests.get(f"{base_url}/references", params={"limit": limit, "fields": "title"}, timeout=5).json()
            c_data = requests.get(f"{base_url}/citations", params={"limit": limit, "fields": "title"}, timeout=5).json()
            refs = [r['citedPaper']['title'] for r in r_data.get('data', []) if r.get('citedPaper')]
            cits = [c['citingPaper']['title'] for c in c_data.get('data', []) if c.get('citingPaper')]
        return data.get("citationCount", 0), refs, cits
    except: return 0, [], []

# --- INTERFAZ ---
st.title("🎓 AcademiGraph Pro: Inteligencia y Exportación")

with st.sidebar:
    st.header("⚙️ Configuración")
    user_email = st.text_input("Email", "investigador@institucion.edu")
    n_results = st.slider("Artículos Base", 5, 20, 10)
    st.info("Ahora el CSV incluirá la genealogía completa (Antecedentes y Citas).")

query = st.text_input("Término de búsqueda:")

if st.button("🚀 Iniciar Mapeo"):
    if query:
        # 1. Simulación de búsqueda (aquí llamarías a tus motores OA, Crossref, etc.)
        # Para este ejemplo, supongamos que 'data_base' son tus resultados verdes
        data_base = [] # ... resultados de los motores ...

        with st.status("Construyendo base de datos expandida...", expanded=True) as status:
            G = nx.DiGraph()
            lista_para_csv = [] # AQUÍ GUARDAREMOS TODO
            
            for art in data_base:
                citas_r, refs, cits = obtener_metadatos_completos(art['DOI'], art['Título'])
                
                # AÑADIR ARTÍCULO PRINCIPAL AL CSV
                lista_para_csv.append({
                    "Título": art['Título'],
                    "Relación": "PRINCIPAL (Resultado de búsqueda)",
                    "Origen": art['Fuente'],
                    "Vinculado a": "N/A"
                })

                # AÑADIR REFERENCIAS (ANTECEDENTES) AL CSV Y GRAFO
                for r in refs:
                    lista_para_csv.append({
                        "Título": r,
                        "Relación": "REFERENCIA (Antecedente)",
                        "Origen": "Semantic Scholar",
                        "Vinculado a": art['Título']
                    })
                    G.add_node(r, color='#FF5722', title="Referencia")
                    G.add_edge(art['Título'], r, color='#FF5722')

                # AÑADIR CITAS (IMPACTO) AL CSV Y GRAFO
                for c in cits:
                    lista_para_csv.append({
                        "Título": c,
                        "Relación": "CITA (Impacto futuro)",
                        "Origen": "Semantic Scholar",
                        "Vinculado a": art['Título']
                    })
                    G.add_node(c, color='#2196F3', title="Cita")
                    G.add_edge(c, art['Título'], color='#2196F3')
                
                G.add_node(art['Título'], color='#4CAF50', size=25)

            st.session_state.full_data = lista_para_csv
            st.session_state.grafo = G
            status.update(label="Análisis y lista de descarga listos.", state="complete")

# --- RENDERIZADO Y DESCARGA ---
if 'full_data' in st.session_state:
    df_export = pd.DataFrame(st.session_state.full_data)
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("🌐 Visualización Dinámica")
        net = Network(height="600px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
        net.from_nx(st.session_state.grafo)
        components.html(net.generate_html(), height=650)

    with col2:
        st.subheader("💾 Descargar Resultados")
        st.write(f"Se han procesado **{len(df_export)}** registros en total (incluyendo red de citas).")
        
        # Botón para descargar TODO
        csv_full = df_export.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Descargar RED COMPLETA (CSV)",
            data=csv_full,
            file_name="red_academica_completa.csv",
            mime="text/csv",
            help="Descarga el listado de artículos base, sus referencias y sus citas."
        )
        
        st.divider()
        st.dataframe(df_export, height=400)
