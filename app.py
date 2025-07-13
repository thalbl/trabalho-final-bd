from flask import Flask, render_template, request
import mysql.connector
import matplotlib
from functools import lru_cache
import time
from typing import Dict, List, Any, Optional, Union

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
import seaborn as sns

app = Flask(__name__)

# Configurações do banco de dados
db_config = {
    'user': '',
    'password': '',
    'host': '',
    'port': 3306,
    'database': '',
    'raise_on_warnings': True,
    'auth_plugin': '',
    'pool_name': '',
    'pool_size': 5,
    'autocommit': True
}

# Cache para gráficos (em produção, use Redis ou similar)
chart_cache: Dict[str, tuple] = {}
CACHE_DURATION = 300  # 5 minutos

def get_db_connection():
    return mysql.connector.connect(**db_config)

def is_cache_valid(cache_key: str) -> bool:
    """Verifica se o cache ainda é válido"""
    if cache_key in chart_cache:
        timestamp, _ = chart_cache[cache_key]
        return time.time() - timestamp < CACHE_DURATION
    return False

def get_cached_chart(cache_key: str) -> Optional[str]:
    """Obtém gráfico do cache se válido"""
    if is_cache_valid(cache_key):
        return chart_cache[cache_key][1]
    return None

def set_cached_chart(cache_key: str, plot_url: str) -> None:
    """Armazena gráfico no cache"""
    chart_cache[cache_key] = (time.time(), plot_url)

def safe_get(dict_obj: Any, key: str, default: Any = None) -> Any:
    """Função segura para acessar valores de dicionário"""
    if isinstance(dict_obj, dict):
        return dict_obj.get(key, default)
    return default

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/autores')
def autores():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Cache key para esta consulta
    cache_key = 'autores_chart'
    cached_plot = get_cached_chart(cache_key)
    
    if cached_plot:
        # Query otimizada apenas para dados da tabela
        query = """
        SELECT A.nome AS nome_autor, L.titulo AS titulo_livro 
        FROM Autor AS A 
        LEFT JOIN Escreve AS E ON A.id_autor = E.fk_Autor_id_autor 
        LEFT JOIN Livro AS L ON E.fk_Livro_id = L.id
        LIMIT 1000
        """
        cursor.execute(query)
        autores_livros = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('autores.html',
                               autores_livros=autores_livros,
                               plot_url=cached_plot)

    # Query otimizada com COUNT direto no banco - apenas autores com livros
    query_optimized = """
    SELECT 
        A.id_autor,
        A.nome AS nome_autor,
        COUNT(E.fk_Livro_id) AS total_livros
    FROM Autor AS A 
    INNER JOIN Escreve AS E ON A.id_autor = E.fk_Autor_id_autor 
    GROUP BY A.id_autor, A.nome
    HAVING COUNT(E.fk_Livro_id) > 0
    ORDER BY total_livros DESC
    """

    cursor.execute(query_optimized)
    autores_count = cursor.fetchall()

    # Query separada para detalhes dos livros (mais eficiente) - apenas autores com livros
    query_livros = """
    SELECT 
        A.id_autor,
        A.nome AS nome_autor, 
        L.titulo AS titulo_livro 
    FROM Autor AS A 
    INNER JOIN Escreve AS E ON A.id_autor = E.fk_Autor_id_autor 
    INNER JOIN Livro AS L ON E.fk_Livro_id = L.id
    ORDER BY A.nome, L.titulo
    LIMIT 1000
    """
    
    cursor.execute(query_livros)
    autores_livros = cursor.fetchall()

    # Gerar gráfico apenas se não estiver em cache
    if autores_count:
        autor_nomes = [str(safe_get(a, 'nome_autor', '')) for a in autores_count[:20]]  # Limitar a 20 autores
        total_livros = [int(safe_get(a, 'total_livros', 0)) for a in autores_count[:20]]

        plt.figure(figsize=(12, 8))
        sns.barplot(
            x=autor_nomes,
            y=total_livros,
            palette='viridis'
        )
        plt.title('Distribuição de Livros por Autor (Top 20)')
        plt.xlabel('Autores')
        plt.ylabel('Quantidade de Livros')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()

        img = io.BytesIO()
        plt.savefig(img, format='png', dpi=100)  # Reduzir DPI para performance
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')
        plt.close()
        
        # Armazenar no cache
        set_cached_chart(cache_key, plot_url)
    else:
        plot_url = None

    cursor.close()
    conn.close()

    return render_template('autores.html',
                           autores_count=autores_count,
                           autores_livros=autores_livros,
                           plot_url=plot_url)

@app.route('/generos')
def generos():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Query otimizada com índices sugeridos
    query = """
    SELECT 
        P.fk_Genero_Nome as genero, 
        AVG(I.nota) AS media_notas_genero, 
        COUNT(DISTINCT P.fk_Livro_id) AS total_livros 
    FROM 
        Possui AS P 
    INNER JOIN 
        Interacao AS I ON P.fk_Livro_id = I.fk_Livro_id 
    GROUP BY 
        P.fk_Genero_Nome 
    HAVING 
        AVG(I.nota) > 4.0 AND COUNT(DISTINCT P.fk_Livro_id) > 5
    ORDER BY 
        media_notas_genero DESC;
    """

    cursor.execute(query)
    generos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('generos.html', generos=generos)

@app.route('/livros_sem_interacao')
def livros_sem_interacao():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Query super otimizada - apenas dados essenciais, limitada a 10 resultados
    query = """
    SELECT 
        L.id,
        L.titulo, 
        L.editora, 
        L.nota_media
    FROM 
        Livro AS L 
    WHERE 
        NOT EXISTS (SELECT 1 FROM Interacao I WHERE I.fk_Livro_id = L.id)
    ORDER BY L.titulo
    LIMIT 10;
    """

    cursor.execute(query)
    livros = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('livros_sem_interacao.html', livros=livros)

@app.route('/usuarios_max_nota')
def usuarios_max_nota():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Aumentar o limite do GROUP_CONCAT
    cursor.execute("SET SESSION group_concat_max_len = 1000000;")

    # Obter parâmetro de limite da URL
    limit = request.args.get('limit', '10', type=int)
    if limit not in [5, 10, 20]:
        limit = 10

    query = """
    SELECT 
        U.id AS usuario_id,
        COUNT(*) AS total_max_notas,
        GROUP_CONCAT(
            DISTINCT CONCAT(CAST(L.id AS CHAR), ':', L.titulo)
            ORDER BY L.titulo 
            SEPARATOR '; '
        ) AS livros_avaliados
    FROM 
        Interacao AS I 
    JOIN 
        Usuario AS U ON I.fk_Usuario_id = U.id
    JOIN 
        Livro AS L ON I.fk_Livro_id = L.id
    WHERE 
        I.nota = 5
    GROUP BY 
        U.id
    ORDER BY 
        total_max_notas DESC
    LIMIT %s;
    """

    cursor.execute(query, (limit,))
    usuarios = cursor.fetchall()

    # Gerar gráfico de barras para os top usuários
    if usuarios:
        usuario_ids = [f"Usuário {str(safe_get(u, 'usuario_id', ''))[:8]}" for u in usuarios]
        total_notas = [int(safe_get(u, 'total_max_notas', 0)) for u in usuarios]

        plt.figure(figsize=(12, 8))
        sns.barplot(
            x=usuario_ids,
            y=total_notas,
            palette='mako'
        )
        plt.title(f'Top {limit} Usuários com Mais Notas Máximas')
        plt.xlabel('Usuários')
        plt.ylabel('Notas Máximas (5)')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()

        # Converter gráfico para imagem
        img = io.BytesIO()
        plt.savefig(img, format='png', dpi=100)
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')
        plt.close()
    else:
        plot_url = None

    cursor.close()
    conn.close()

    return render_template('usuarios_max_nota.html', 
                           usuarios=usuarios, 
                           plot_url=plot_url, 
                           current_limit=limit)

@app.route('/livro/<int:livro_id>')
def detalhes_livro(livro_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Buscar informações do livro
    query_livro = """
    SELECT 
        L.id,
        L.titulo,
        L.descricao,
        L.capa,
        L.editora,
        L.isbn,
        L.nota_media,
        GROUP_CONCAT(DISTINCT A.nome SEPARATOR ', ') AS autores,
        GROUP_CONCAT(DISTINCT G.Nome SEPARATOR ', ') AS generos
    FROM 
        Livro AS L
    LEFT JOIN 
        Escreve AS E ON L.id = E.fk_Livro_id
    LEFT JOIN 
        Autor AS A ON E.fk_Autor_id_autor = A.id_autor
    LEFT JOIN 
        Possui AS P ON L.id = P.fk_Livro_id
    LEFT JOIN 
        Genero AS G ON P.fk_Genero_Nome = G.Nome
    WHERE 
        L.id = %s
    GROUP BY 
        L.id;
    """

    cursor.execute(query_livro, (livro_id,))
    livro = cursor.fetchone()

    if not livro:
        cursor.close()
        conn.close()
        return "Livro não encontrado", 404

    # Buscar interações do livro
    query_interacoes = """
    SELECT 
        I.nota,
        I.comentario,
        I.ultima_atualizacao,
        I.status,
        I.comeco,
        I.fim,
        U.id AS usuario_id
    FROM 
        Interacao AS I
    JOIN 
        Usuario AS U ON I.fk_Usuario_id = U.id
    WHERE 
        I.fk_Livro_id = %s
    ORDER BY 
        I.ultima_atualizacao DESC
    LIMIT 50;
    """

    cursor.execute(query_interacoes, (livro_id,))
    interacoes = cursor.fetchall()

    # Calcular estatísticas
    query_stats = """
    SELECT 
        COUNT(*) AS total_avaliacoes,
        AVG(nota) AS media_notas,
        COUNT(CASE WHEN nota = 5 THEN 1 END) AS notas_maximas,
        COUNT(CASE WHEN nota >= 4 THEN 1 END) AS notas_altas
    FROM 
        Interacao
    WHERE 
        fk_Livro_id = %s;
    """

    cursor.execute(query_stats, (livro_id,))
    estatisticas = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template('detalhes_livro.html',
                           livro=livro,
                           interacoes=interacoes,
                           estatisticas=estatisticas)

@app.route('/media_livros_autor')
def media_livros_autor():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Cache key para esta consulta
    cache_key = 'media_livros_autor_chart'
    cached_plot = get_cached_chart(cache_key)
    
    if cached_plot:
        # Query otimizada apenas para dados
        query_media = """
        SELECT 
            AVG(ContagemLivros.TotalLivros) AS media_livros_por_autor 
        FROM ( 
            SELECT 
                fk_Autor_id_autor, 
                COUNT(fk_Livro_id) AS TotalLivros 
            FROM 
                Escreve 
            GROUP BY 
                fk_Autor_id_autor 
        ) AS ContagemLivros;
        """
        cursor.execute(query_media)
        result = cursor.fetchone()
        media_geral = safe_get(result, 'media_livros_por_autor', 0.0)

        query_distribuicao = """
        SELECT 
            A.nome AS autor,
            COUNT(E.fk_Livro_id) AS total_livros
        FROM 
            Autor AS A
        LEFT JOIN 
            Escreve AS E ON A.id_autor = E.fk_Autor_id_autor
        GROUP BY 
            A.id_autor, A.nome
        ORDER BY 
            total_livros DESC
        LIMIT 100;
        """
        cursor.execute(query_distribuicao)
        distribuicao = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('media_livros_autor.html',
                               media_geral=media_geral,
                               distribuicao=distribuicao,
                               plot_url=cached_plot)

    # Calcular média geral com query otimizada
    query_media = """
    SELECT 
        AVG(ContagemLivros.TotalLivros) AS media_livros_por_autor 
    FROM ( 
        SELECT 
            fk_Autor_id_autor, 
            COUNT(fk_Livro_id) AS TotalLivros 
        FROM 
            Escreve 
        GROUP BY 
            fk_Autor_id_autor 
    ) AS ContagemLivros;
    """

    cursor.execute(query_media)
    result = cursor.fetchone()
    media_geral = safe_get(result, 'media_livros_por_autor', 0.0)

    # Obter distribuição por autor com LIMIT
    query_distribuicao = """
    SELECT 
        A.nome AS autor,
        COUNT(E.fk_Livro_id) AS total_livros
    FROM 
        Autor AS A
    LEFT JOIN 
        Escreve AS E ON A.id_autor = E.fk_Autor_id_autor
    GROUP BY 
        A.id_autor, A.nome
    ORDER BY 
        total_livros DESC
    LIMIT 100;
    """

    cursor.execute(query_distribuicao)
    distribuicao = cursor.fetchall()

    # Gerar histograma apenas se não estiver em cache
    if distribuicao:
        totais = [int(safe_get(d, 'total_livros', 0)) for d in distribuicao]

        plt.figure(figsize=(10, 6))
        sns.histplot(totais, bins=20, kde=True, color='skyblue')
        plt.axvline(float(media_geral), color='red', linestyle='dashed', linewidth=2,
                    label=f'Média: {float(media_geral):.2f}')
        plt.title('Distribuição de Livros por Autor')
        plt.xlabel('Número de Livros')
        plt.ylabel('Número de Autores')
        plt.legend()

        img = io.BytesIO()
        plt.savefig(img, format='png', dpi=100)
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')
        plt.close()
        
        # Armazenar no cache
        set_cached_chart(cache_key, plot_url)
    else:
        plot_url = None

    cursor.close()
    conn.close()

    return render_template('media_livros_autor.html',
                           media_geral=media_geral,
                           distribuicao=distribuicao,
                           plot_url=plot_url)

@app.route('/buscar')
def buscar():
    query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    if not query:
        return render_template('busca.html', livros=[], query='', total_results=0, page=1, total_pages=0)
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    search_query = f"%{query}%"
    
    # Query de contagem (apenas por título)
    count_query = """
    SELECT COUNT(*) as total
    FROM Livro AS L
    WHERE L.titulo LIKE %s
    """
    
    cursor.execute(count_query, (search_query,))  # Único parâmetro
    result = cursor.fetchone()
    total_results = safe_get(result, 'total', 0)
    
    # Paginação
    total_pages = (total_results + per_page - 1) // per_page
    offset = (page - 1) * per_page
    
    # Query principal (apenas por título)
    main_query = """
    SELECT 
        L.id,
        L.titulo,
        L.capa,
        GROUP_CONCAT(DISTINCT A.nome SEPARATOR ', ') AS autores,
        MIN(A.id_autor) AS autor_id
    FROM Livro AS L
    LEFT JOIN Escreve AS E ON L.id = E.fk_Livro_id
    LEFT JOIN Autor AS A ON E.fk_Autor_id_autor = A.id_autor
    WHERE L.titulo LIKE %s
    GROUP BY L.id, L.titulo, L.capa
    ORDER BY L.titulo
    LIMIT %s OFFSET %s
    """
    
    cursor.execute(main_query, (search_query, per_page, offset))
    livros = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('busca.html',
                           livros=livros,
                           query=query,
                           total_results=total_results,
                           page=page,
                           total_pages=total_pages)
                           
@app.route('/autor/<int:autor_id>')
def detalhes_autor(autor_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Buscar informações do autor
    query_autor = """
    SELECT 
        A.id_autor,
        A.nome
    FROM 
        Autor AS A
    WHERE 
        A.id_autor = %s
    """
    
    cursor.execute(query_autor, (autor_id,))
    autor = cursor.fetchone()
    
    if not autor:
        cursor.close()
        conn.close()
        return "Autor não encontrado", 404
    
    # Buscar livros do autor
    query_livros = """
    SELECT 
        L.id,
        L.titulo,
        L.capa
    FROM 
        Livro AS L
    JOIN 
        Escreve AS E ON L.id = E.fk_Livro_id
    WHERE 
        E.fk_Autor_id_autor = %s
    ORDER BY 
        L.titulo
    """
    
    cursor.execute(query_livros, (autor_id,))
    livros = cursor.fetchall()
    
    # Calcular estatísticas do autor
    query_stats = """
    SELECT 
        COUNT(DISTINCT L.id) AS total_livros,
        AVG(I.nota) AS media_notas,
        COUNT(I.fk_Livro_id) AS total_avaliacoes
    FROM 
        Livro AS L
    JOIN 
        Escreve AS E ON L.id = E.fk_Livro_id
    LEFT JOIN 
        Interacao AS I ON L.id = I.fk_Livro_id
    WHERE 
        E.fk_Autor_id_autor = %s
    """
    
    cursor.execute(query_stats, (autor_id,))
    stats = cursor.fetchone()
    
    # Buscar gêneros mais frequentes do autor
    query_generos = """
    SELECT 
        G.Nome AS nome,
        COUNT(DISTINCT L.id) AS total_livros
    FROM 
        Genero AS G
    JOIN 
        Possui AS P ON G.Nome = P.fk_Genero_Nome
    JOIN 
        Livro AS L ON P.fk_Livro_id = L.id
    JOIN 
        Escreve AS E ON L.id = E.fk_Livro_id
    WHERE 
        E.fk_Autor_id_autor = %s
    GROUP BY 
        G.Nome
    ORDER BY 
        total_livros DESC
    LIMIT 10
    """
    
    cursor.execute(query_generos, (autor_id,))
    generos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('detalhes_autor.html',
                           autor=autor,
                           livros=livros,
                           total_livros=safe_get(stats, 'total_livros', 0),
                           media_notas=safe_get(stats, 'media_notas', 0.0),
                           total_avaliacoes=safe_get(stats, 'total_avaliacoes', 0),
                           generos=generos)

# Rota para limpar cache (útil para desenvolvimento)
@app.route('/clear_cache')
def clear_cache():
    global chart_cache
    chart_cache.clear()
    return {'message': 'Cache limpo com sucesso'}

if __name__ == '__main__':
    app.run(debug=True)