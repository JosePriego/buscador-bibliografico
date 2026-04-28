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
    page_title="AcademiGraph Pro | Global Intel", 
    layout="wide", 
    page_icon="⚖️"
)

# --- ESTILOS PERSONALIZADOS ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; font-weight: bold; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #1c83e1; color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. MOTORES DE BÚSQUEDA (EL HEXÁGONO FEDERADO) ---

def buscar_federado_total(materia, limite, email, perfil):
    resultados = []
    
    # MOTOR 1: OPENALEX (Incluye datos de Dimensions y Ciencias Sociales)
    def buscar_oa():
        try:
            params = {"search": materia, "per-page": limite, "mailto": email, "sort": "cited_by_count:desc"}
            res = requests.get("https://api.openalex.org/works", params=params, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    doi_url = item.get("doi")
                    resultados.append({
                        "Fuente": "OpenAlex/Dimensions", "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": doi_url.replace("https://doi.org/", "") if doi_url else None,
                        "Citas": int(item.get("cited_by_count", 0))
                    })
        except: pass

    # MOTOR 2: CORE (Acceso Abierto Global)
    def buscar_core():
        try:
            res = requests.get(f"https://api.core.ac.uk/v3/search/works", 
                               params={"q": materia, "limit": limite}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    resultados.append({
                        "Fuente": "CORE", "Título": item.get("title"),
                        "Autor": item.get("authors", [{}])[0].get("name", "N/A") if item.get("authors") else "N/A",
                        "DOI": item.get("doi"), "Citas": 0
                    })
        except: pass

    # MOTOR 3: PUBMED (Solo si no es perfil Econ/Derecho estricto)
    def buscar_pubmed():
        if perfil == "Derecho/Economía": return
        try:
            base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
            s_res = requests.get(f"{base_url}esearch.fcgi", params={"db": "pubmed", "term": materia, "retmax": limite, "retmode": "json"})
            ids = s_res.json().get("esearchresult", {}).get("idlist", [])
            if ids:
                f_res = requests.get(f"{base_url}esummary.fcgi", params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
                summaries = f_res.json().get("result", {})
                for uid in ids:
                    paper = summaries.get(uid, {})
                    resultados.append({
                        "Fuente": "PubMed", "Título": paper.get("title"),
                        "Autor": paper.get("authors", [{}])[0].get("name", "N/A") if paper.get("authors") else "N/A",
                        "DOI": paper.get("elocationid", "").replace("doi: ", ""), "Citas": 0
                    })
        except: pass

    # MOTOR 4: REPEC / ECONPAPERS (Específico para Económicas)
    def buscar_repec():
        if perfil == "General": return
        try:
            res = requests.get("https://api.crossref.org/works", 
                               params={"query": f"{materia} RePEc EconPapers", "rows": limite, "sort": "is-referenced-by-count"}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    resultados.append({
                        "Fuente": "RePEc/EconPapers", "Título": item.get("title", [""])[0],
                        "Autor": item.get("author", [{}])[0].get("family", "N/A") if item.get("author") else "N/A",
                        "DOI": item.get("DOI"), "Citas": int(item.get("is-referenced-by-count", 0))
                    })
        except: pass

    # MOTOR 5: CROSSREF (Impacto General)
    def buscar_cr():
        try:
            res = requests.get("https://api.crossref.org/works", 
                               params={"query": materia, "rows": limite, "mailto": email, "sort": "is-referenced-by-count", "order": "desc"}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    resultados.append({
                        "Fuente": "Crossref", "Título": item.get("title", [""])[0],
                        "Autor": item.get("author", [{}])[0].get("family", "N/A") if item.get("author") else "N/A",
                        "DOI": item.get("DOI"), "Citas": int(item.get("is-referenced-by-count", 0))
                    })
        except: pass

    # MOTOR 6: UCO (Repositorio Institucional)
    def buscar_uco():
        try:
            url = "https://mezquita.uco.es/primaws/rest/pub/pnxs"
            params = {"q": f"any,contains,{materia}", "limit": limite, "vid": "34CBUA_UCO:VU1", "tab": "Everything", "scope": "MyInst_and_CI", "inst": "34CBUA_UCO"}
            res = requests.get(url, params=params, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("docs", []):
                    pnx = item.get("pnx", {})
                    disp = pnx.get("display", {})
                    resultados.append({
                        "Fuente": "UCO", "Título": disp.get("title", [""])[0],
                        "Autor": disp.get("creator", ["N/A"])[0], 
                        "DOI": pnx.get("addata", {}).get("doi", [None])[0], "Citas": 0
                    })
        except: pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_core)
        executor.submit(buscar_pubmed)
        executor.submit(buscar_repec)
        executor.submit(buscar_cr)
        executor.submit(buscar_uco)
        
    return resultados

# --- 2. MOTOR DE RED (BIDIRECCIONAL) ---

def obtener_red_completa(doi, titulo, limite_red=5):
    refs, cits = [], []
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            p_id = data.get("paperId") if doi else data.get("data", [{}])[0].get("paperId")
            if p_id:
                # Referencias (Rojo)
                r_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/references", params={"limit": limite_red, "fields": "title"}, timeout=10)
                if r_res.status_code == 200:
                    refs = [i['citedPaper']['title'] for i in r_res.json().get('data', []) if i.get('citedPaper')]
                
                time.sleep(0.6) 

                # Citas (Azul)
                c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", params={"limit": limite_red, "fields": "title"}, timeout=10)
                if c_res.status_code == 200:
                    cits = [i['citingPaper']['title'] for i in c_res.json().get('data', []) if i.get('citingPaper')]
    except: pass
    return refs, cits

# --- 3. INTERFAZ STREAMLIT ---

st.title("⚖️ AcademiGraph Pro | Global Search")
st.markdown("Plataforma de vigilancia científica para todas las facultades (**Derecho, Económicas, Medicina, Ciencias e Ingeniería**).")

with st.sidebar:
    st.header("⚙️ Configuración")
    perfil = st.selectbox("Perfil de Búsqueda", ["General", "Derecho/Economía"])
    user_email = st.text_input("Email Investigador", "investigador@uco.es")
    n_results = st.slider("Resultados por motor", 1, 10, 5)
    st.divider()
    st.markdown("""
    **Leyenda de Red:**
    - 🟢 Centro: Artículos Top.
    - 🔴 Saliente: Referencias.
    - 🔵 Entrante: Citas.
    """)

query = st.text_input("Tema de investigación:", placeholder="Ej: Blockchain en el Derecho Mercantil")

if st.button("🚀 Lanzar Investigación de Alto Impacto"):
    if query:
        with st.status("Interrogando repositorios globales...", expanded=True) as s:
            data_base = buscar_federado_total(query, n_results, user_email, perfil)
            s.write(f"✅ Se han localizado {len(data_base)} artículos núcleo de alto impacto.")
            
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

            s.update(label="Mapa de impacto generado con éxito.", state="complete")

        # VISUALIZACIÓN
        col_m, col_d = st.columns([2, 1])
        
        with col_m:
            st.markdown("### 🕸️ Mapa de Influencia Global")
            net = Network(height="700px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            net.repulsion(node_distance=220, spring_length=200)
            components.html(net.generate_html(), height=750)

        with col_data_col := col_d:
            st.markdown("### 📊 Ranking de Resultados")
            df = pd.DataFrame(data_base)
            if not df.empty:
                df["Citas"] = pd.to_numeric(df["Citas"], errors='coerce').fillna(0).astype(int)
                df_sorted = df.sort_values(by="Citas", ascending=False)
                st.dataframe(df_sorted, use_container_width=True)
                st.download_button("📥 Descargar CSV de Impacto", df_sorted.to_csv(index=False).encode('utf-8'), "reporte_investigacion.csv", "text/csv")
            else:
                st.info("Sin resultados.")
    else:
        st.warning("Introduce un término de búsqueda.")
