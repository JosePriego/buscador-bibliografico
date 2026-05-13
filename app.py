import streamlit as st
import requests
import concurrent.futures
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import pandas as pd
from typing import List, Dict

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="AcademiGraph Pro | Intelligence Edition", 
    layout="wide", 
    page_icon="🎓"
)

# --- ESTILOS VISUALES ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .main-card { background-color: #1e2130; padding: 20px; border-radius: 15px; border: 1px solid #30363d; }
    .stButton>button { width: 100%; border-radius: 8px; background: linear-gradient(90deg, #2e7bcf, #1c83e1); color: white; border: none; transition: 0.3s; }
    .stButton>button:hover { opacity: 0.8; transform: translateY(-2px); }
    </style>
    """, unsafe_allow_html=True)

# --- UTILIDADES Y LIMPIEZA ---

def limpiar_resultados(resultados: List[Dict]) -> List[Dict]:
    """Elimina duplicados basados en DOI o Título."""
    vistos = set()
    unicos = []
    for item in resultados:
        identificador = item.get("DOI") or item.get("Título").lower().strip()
        if identificador not in vistos:
            vistos.add(identificador)
            unicos.append(item)
    return unicos

# --- MOTORES DE BÚSQUEDA ---

class AcademicEngine:
    def __init__(self, email):
        self.headers = {"User-Agent": f"AcademiGraphPro/2.0 (mailto:{email})"}
        self.email = email

    def fetch_openalex(self, query, limite, campo):
        try:
            params = {"per-page": limite, "mailto": self.email, "sort": "cited_by_count:desc"}
            filters = {
                "ORCID": f"author.orcid:https://orcid.org/{query}",
                "Título": f"title.search:{query}",
                "Autor (Nombre)": f"authorships.author.display_name.search:{query}"
            }
            if campo in filters: params["filter"] = filters[campo]
            else: params["search"] = query
            
            res = requests.get("https://api.openalex.org/works", params=params, timeout=10)
            return [{
                "Fuente": "OpenAlex", "Título": i.get("title"),
                "Autor": i.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                "DOI": i.get("doi", "").replace("https://doi.org/", "") if i.get("doi") else None,
                "Citas": i.get("cited_by_count", 0)
            } for i in res.json().get("results", [])]
        except: return []

    def fetch_crossref(self, query, limite, campo):
        try:
            params = {"rows": limite, "mailto": self.email, "sort": "is-referenced-by-count", "order": "desc"}
            q_map = {"Título": "query.title", "Autor (Nombre)": "query.author"}
            params[q_map.get(campo, "query")] = query
            
            res = requests.get("https://api.crossref.org/works", params=params, timeout=10)
            return [{
                "Fuente": "Crossref", "Título": i.get("title", ["N/A"])[0],
                "Autor": i.get("author", [{}])[0].get("family", "N/A"),
                "DOI": i.get("DOI"), "Citas": i.get("is-referenced-by-count", 0)
            } for i in res.json().get("message", {}).get("items", [])]
        except: return []

# --- MOTOR DE RED (SEMANTIC SCHOLAR) ---

@st.cache_data(ttl=3600)
def fetch_network_data(doi, titulo, limit=5):
    """Obtiene referencias y citas de un artículo específico."""
    try:
        # Paso 1: Obtener ID de Semantic Scholar
        url_search = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res = requests.get(url_search, timeout=8).json()
        paper_id = res.get("paperId") if doi else res.get("data", [{}])[0].get("paperId")
        
        if not paper_id: return [], []

        # Paso 2: Obtener Red (Referencias y Citas) en paralelo
        base_url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
        refs = requests.get(f"{base_url}/references", params={"limit": limit, "fields": "title"}, timeout=5).json()
        cits = requests.get(f"{base_url}/citations", params={"limit": limit, "fields": "title"}, timeout=5).json()
        
        return ([r['citedPaper']['title'] for r in refs.get('data', []) if r.get('citedPaper')],
                [c['citingPaper']['title'] for c in cits.get('data', []) if c.get('citingPaper')])
    except: return [], []

# --- INTERFAZ PRINCIPAL ---

st.title("🎓 AcademiGraph Pro")
st.caption("Inteligencia Bibliométrica Avanzada para Investigadores")

with st.sidebar:
    st.header("⚙️ Configuración")
    campo_busqueda = st.selectbox("Buscar por:", ["Palabras Clave", "Título", "Autor (Nombre)", "ORCID"])
    user_email = st.text_input("Email (Polite Pool)", "investigador@institucion.edu")
    n_results = st.slider("Resultados por motor", 5, 30, 10)
    st.divider()
    st.info("El grafo muestra la genealogía del conocimiento: de dónde viene (rojo) y hacia dónde va (azul).")

query = st.text_input(f"Introduce el {campo_busqueda}:", placeholder="Ej: Quantum Machine Learning")

# Inicializar estados de sesión
if 'data_final' not in st.session_state: st.session_state.data_final = None
if 'grafo' not in st.session_state: st.session_state.grafo = None

if st.button("🚀 Lanzar Investigación"):
    if not query:
        st.warning("Por favor, introduce un término de búsqueda.")
    else:
        engine = AcademicEngine(user_email)
        
        with st.status("🔍 Consultando bases de datos científicas...", expanded=True) as status:
            # 1. Búsqueda Concurrente
            with concurrent.futures.ThreadPoolExecutor() as executor:
                f1 = executor.submit(engine.fetch_openalex, query, n_results, campo_busqueda)
                f2 = executor.submit(engine.fetch_crossref, query, n_results, campo_busqueda)
                resultados_raw = f1.result() + f2.result()
            
            data_unicos = limpiar_resultados(resultados_raw)
            status.write(f"✅ Se encontraron {len(data_unicos)} artículos únicos.")

            # 2. Construcción de Red Paralelizada
            status.write("🕸️ Mapeando conexiones bibliográficas...")
            G = nx.DiGraph()
            
            def procesar_nodo(art):
                r, c = fetch_network_data(art['DOI'], art['Título'])
                return art, r, c

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(procesar_nodo, art) for art in data_unicos]
                for future in concurrent.futures.as_completed(futures):
                    art, refs, cits = future.result()
                    
                    # Añadir nodo base
                    G.add_node(art['Título'], color='#4CAF50', size=25, title=f"Autor: {art['Autor']}")
                    
                    for r in refs:
                        G.add_node(r, color='#FF5722', size=12, title="Referencia")
                        G.add_edge(art['Título'], r, color='#FF5722', weight=1)
                    
                    for c in cits:
                        G.add_node(c, color='#2196F3', size=12, title="Cita Recibida")
                        G.add_edge(c, art['Título'], color='#2196F3', weight=1)

            st.session_state.data_final = data_unicos
            st.session_state.grafo = G
            status.update(label="¡Análisis completado!", state="complete")

# --- RENDERIZADO DE RESULTADOS ---

if st.session_state.grafo:
    col_map, col_stats = st.columns([2, 1])

    with col_map:
        st.subheader("🌐 Mapa de Conocimiento")
        net = Network(height="600px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
        net.from_nx(st.session_state.grafo)
        
        # Ajuste de física para que el grafo sea legible
        net.set_options("""
        var options = {
          "physics": {
            "forceAtlas2Based": { "gravitationalConstant": -50, "centralGravity": 0.01, "springLength": 100 },
            "minVelocity": 0.75, "solver": "forceAtlas2Based"
          }
        }
        """)
        
        components.html(net.generate_html(), height=650)

    with col_stats:
        st.subheader("📊 Ranking de Impacto")
        df = pd.DataFrame(st.session_state.data_final)
        df = df.sort_values(by="Citas", ascending=False)
        
        st.dataframe(df[["Título", "Autor", "Citas", "Fuente"]], use_container_width=True, hide_index=True)
        
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Descargar Reporte CSV", csv, "analisis_bibliometrico.csv", "text/csv")
