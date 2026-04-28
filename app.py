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
    page_title="AcademiGraph Pro | Explorer", 
    layout="wide", 
    page_icon="🎓"
)

# --- DISEÑO DE INTERFAZ ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; border: none; font-weight: bold; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #1c83e1; color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. MOTORES DE BÚSQUEDA (FEDERADOS) ---

def buscar_federado(materia, limite, email):
    resultados = []
    
    def buscar_oa():
        try:
            res = requests.get("https://api.openalex.org/works", 
                               params={"search": materia, "per-page": limite, "mailto": email}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    doi_url = item.get("doi")
                    resultados.append({
                        "Fuente": "OpenAlex", "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": doi_url.replace("https://doi.org/", "") if doi_url else None
                    })
        except: pass

    def buscar_cr():
        try:
            res = requests.get("https://api.crossref.org/works", 
                               params={"query": materia, "rows": limite, "mailto": email}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    autores = item.get("author", [])
                    autor = autores[0].get('family') if autores else "N/A"
                    resultados.append({
                        "Fuente": "Crossref", "Título": item.get("title", [""])[0],
                        "Autor": autor, "DOI": item.get("DOI")
                    })
        except: pass

    def buscar_uco():
        try:
            url = "https://mezquita.uco.es/primaws/rest/pub/pnxs"
            params = {"q": f"any,contains,{materia}", "limit": limite, "vid": "34CBUA_UCO:VU1", "tab": "Everything", "scope": "MyInst_and_CI", "inst": "34CBUA_UCO"}
            res = requests.get(url, params=params, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("docs", []):
                    pnx = item.get("pnx", {})
                    disp = pnx.get("display", {})
                    doi = pnx.get("addata", {}).get("doi", [None])[0]
                    resultados.append({
                        "Fuente": "UCO", "Título": disp.get("title", [""])[0],
                        "Autor": disp.get("creator", ["N/A"])[0], "DOI": doi
                    })
        except: pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_cr)
        executor.submit(buscar_uco)
        
    return resultados

# --- 2. MOTOR DE RED (BIDIRECCIONAL) ---

def obtener_red_completa(doi, titulo, limite_red=5):
    refs, cits = [], []
    try:
        # 1. Identificar el artículo en Semantic Scholar
        url_id = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res_id = requests.get(url_id, timeout=10)
        
        if res_id.status_code == 200:
            data = res_id.json()
            p_id = data.get("paperId") if doi else data.get("data", [{}])[0].get("paperId")
            
            if p_id:
                # 2. REFERENCIAS (Pasado - Salen del nodo)
                r_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/references", 
                                     params={"limit": limite_red, "fields": "title"}, timeout=10)
                if r_res.status_code == 200:
                    refs = [i['citedPaper']['title'] for i in r_res.json().get('data', []) if i.get('citedPaper')]
                
                time.sleep(0.6) # Evitar bloqueos de API

                # 3. CITAS (Futuro - Entran al nodo)
                c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", 
                                     params={"limit": limite_red, "fields": "title"}, timeout=10)
                if c_res.status_code == 200:
                    cits = [i['citingPaper']['title'] for i in c_res.json().get('data', []) if i.get('citingPaper')]
    except: pass
    return refs, cits

# --- 3. INTERFAZ STREAMLIT ---

st.title("🎓 AcademiGraph Pro")
st.markdown("Herramienta de investigación federada con mapeo bibliométrico bidireccional.")

with st.sidebar:
    st.header("⚙️ Configuración")
    user_email = st.text_input("Email (Polite Pool)", "investigador@institucion.edu")
    n_results = st.slider("Resultados base por fuente", 1, 10, 5)
    st.divider()
    st.markdown("""
    **Leyenda del Mapa:**
    - 🟢 **Verde:** Artículos encontrados.
    - 🔴 **Rojo:** Referencias (Pasado).
    - 🔵 **Azul:** Citas recibidas (Futuro).
    """)

query = st.text_input("Introduce tu término de búsqueda:", placeholder="Ej: Cambio climático en el Mediterráneo")

if st.button("🚀 Ejecutar Investigación"):
    if query:
        # FASE 1: BÚSQUEDA
        with st.status("Consultando bases de datos...", expanded=True) as s:
            data_base = buscar_federado(query, n_results, user_email)
            s.write(f"✅ Se han localizado {len(data_base)} artículos principales.")
            
            # FASE 2: CONSTRUCCIÓN DE RED
            s.write("Generando red de citación bidireccional...")
            grafo = nx.DiGraph()
            progreso = st.progress(0)
            
            for i, art in enumerate(data_base):
                refs, cits = obtener_red_completa(art['DOI'], art['Título'])
                
                # Nodo base (CENTRAL)
                grafo.add_node(art['Título'], color='#4CAF50', size=30, title=f"Fuente: {art['Fuente']}")
                
                # Agregar Referencias (Flecha: Art -> Referencia)
                for r in refs:
                    grafo.add_node(r, color='#FF5722', size=15)
                    grafo.add_edge(art['Título'], r, color='#FF5722', label="referencia")
                
                # Agregar Citas (Flecha: Citador -> Art)
                for c in cits:
                    grafo.add_node(c, color='#2196F3', size=15)
                    grafo.add_edge(c, art['Título'], color='#2196F3', label="cita")
                
                progreso.progress((i + 1) / len(data_base))
                time.sleep(1) # Respetar rate limit de APIs

            s.update(label="¡Análisis bibliométrico listo!", state="complete")

        # FASE 3: VISUALIZACIÓN
        col_map, col_data = st.columns([2, 1])
        
        with col_map:
            st.markdown("### 🕸️ Mapa Interactivo")
            net = Network(height="700px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            net.repulsion(node_distance=200, spring_length=200, spring_strength=0.05)
            
            # Generación del HTML
            net_html = net.generate_html()
            components.html(net_html, height=750)

        with col_data:
            st.markdown("### 📄 Resultados")
            df = pd.DataFrame(data_base)
            st.dataframe(df, use_container_width=True)
            
            # Botón de descarga
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Descargar CSV de Resultados",
                data=csv,
                file_name=f"investigacion_{query.replace(' ','_')}.csv",
                mime="text/csv"
            )
    else:
        st.warning("Por favor, introduce una materia para buscar.")
