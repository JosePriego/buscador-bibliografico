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
    page_title="AcademiGraph Pro | Top Impact", 
    layout="wide", 
    page_icon="🏆"
)

# --- DISEÑO DE INTERFAZ ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; border: none; font-weight: bold; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #1c83e1; color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. MOTORES DE BÚSQUEDA (CON ORDENACIÓN POR IMPACTO) ---

def buscar_federado_top(materia, limite, email):
    resultados = []
    
    def buscar_oa():
        try:
            res = requests.get("https://api.openalex.org/works", 
                               params={
                                   "search": materia, 
                                   "per-page": limite, 
                                   "mailto": email,
                                   "sort": "cited_by_count:desc"
                               }, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    doi_url = item.get("doi")
                    resultados.append({
                        "Fuente": "OpenAlex", 
                        "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": doi_url.replace("https://doi.org/", "") if doi_url else None,
                        "Citas_Aprox": int(item.get("cited_by_count", 0))
                    })
        except: pass

    def buscar_cr():
        try:
            res = requests.get("https://api.crossref.org/works", 
                               params={
                                   "query": materia, 
                                   "rows": limite, 
                                   "mailto": email,
                                   "sort": "is-referenced-by-count",
                                   "order": "desc"
                               }, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    autores = item.get("author", [])
                    autor = autores[0].get('family') if autores else "N/A"
                    resultados.append({
                        "Fuente": "Crossref", 
                        "Título": item.get("title", [""])[0],
                        "Autor": autor, 
                        "DOI": item.get("DOI"),
                        "Citas_Aprox": int(item.get("is-referenced-by-count", 0))
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
                        "Fuente": "UCO", 
                        "Título": disp.get("title", [""])[0],
                        "Autor": disp.get("creator", ["N/A"])[0], 
                        "DOI": doi,
                        "Citas_Aprox": 0 # Valor numérico para evitar errores de sorting
                    })
        except: pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_cr)
        executor.submit(buscar_uco)
        
    return resultados

# --- 2. MOTOR DE RED BIDIRECCIONAL ---

def obtener_red_completa(doi, titulo, limite_red=5):
    refs, cits = [], []
    try:
        url_id = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res_id = requests.get(url_id, timeout=10)
        
        if res_id.status_code == 200:
            data = res_id.json()
            p_id = data.get("paperId") if doi else data.get("data", [{}])[0].get("paperId")
            
            if p_id:
                # Referencias (Rojo)
                r_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/references", 
                                     params={"limit": limite_red, "fields": "title"}, timeout=10)
                if r_res.status_code == 200:
                    refs = [i['citedPaper']['title'] for i in r_res.json().get('data', []) if i.get('citedPaper')]
                
                time.sleep(0.6) 

                # Citas (Azul)
                c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", 
                                     params={"limit": limite_red, "fields": "title"}, timeout=10)
                if c_res.status_code == 200:
                    cits = [i['citingPaper']['title'] for i in c_res.json().get('data', []) if i.get('citingPaper')]
    except: pass
    return refs, cits

# --- 3. INTERFAZ ---

st.title("🎓 AcademiGraph Pro: Impact Search")
st.markdown("Priorizando los artículos con mayor impacto científico.")

with st.sidebar:
    st.header("⚙️ Configuración")
    user_email = st.text_input("Email (Polite Pool)", "investigador@institucion.edu")
    n_results = st.slider("Top artículos por fuente", 1, 10, 5)
    st.divider()
    st.markdown("""
    **Guía de Red:**
    - 🟢 Centro: Tu búsqueda.
    - 🔴 Hacia fuera: Referencias.
    - 🔵 Hacia dentro: Citas recibidas.
    """)

query = st.text_input("Investigar materia:", placeholder="Ej: Inteligencia Artificial")

if st.button("🚀 Iniciar Investigación"):
    if query:
        with st.status("Analizando impacto y conexiones...", expanded=True) as s:
            data_base = buscar_federado_top(query, n_results, user_email)
            s.write(f"✅ Procesando {len(data_base)} artículos núcleo.")
            
            grafo = nx.DiGraph()
            progreso = st.progress(0)
            
            for i, art in enumerate(data_base):
                r_list, c_list = obtener_red_completa(art['DOI'], art['Título'])
                
                # Nodo central
                grafo.add_node(art['Título'], color='#4CAF50', size=30)
                
                for r in r_list:
                    grafo.add_node(r, color='#FF5722', size=15)
                    grafo.add_edge(art['Título'], r, color='#FF5722')
                
                for c in c_list:
                    grafo.add_node(c, color='#2196F3', size=15)
                    grafo.add_edge(c, art['Título'], color='#2196F3')
                
                progreso.progress((i + 1) / len(data_base))
                time.sleep(0.8)

            s.update(label="¡Mapa completado!", state="complete")

        col_map, col_data = st.columns([2, 1])
        
        with col_map:
            st.markdown("### 🕸️ Visualización de Impacto")
            net = Network(height="700px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            net.repulsion(node_distance=220, spring_length=200)
            components.html(net.generate_html(), height=750)

        with col_data:
            st.markdown("### 📊 Ranking de Influencia")
            df = pd.DataFrame(data_base)
            
            if not df.empty:
                # Asegurar orden numérico
                df["Citas_Aprox"] = pd.to_numeric(df["Citas_Aprox"], errors='coerce').fillna(0).astype(int)
                df_sorted = df.sort_values(by="Citas_Aprox", ascending=False)
                
                st.dataframe(df_sorted, use_container_width=True)
                
                csv = df_sorted.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Descargar CSV Ordenado", csv, "reporte_impacto.csv", "text/csv")
            else:
                st.info("Sin resultados.")
    else:
        st.warning("Introduce un término.")
