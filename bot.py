# -*- coding: utf-8 -*-

import os
import hashlib
import json
from datetime import datetime, timedelta, time
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from supabase import create_client
from google import genai
import numpy as np

# ===== Configuração =====
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

variaveis_obrigatorias = {
    "TELEGRAM_TOKEN": TOKEN,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "GEMINI_API_KEY": GEMINI_API_KEY,
}
variaveis_faltando = [
    nome for nome, valor in variaveis_obrigatorias.items() if not valor
]
if variaveis_faltando:
    raise RuntimeError(
        f"Variáveis de ambiente ausentes: {', '.join(variaveis_faltando)}"
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Estados da conversa
AGUARDANDO_DURACAO = 1
ESCOLHENDO_MODO_HORARIO = 2
ESCOLHENDO_DIA = 3
ESCOLHENDO_HORARIO = 4
ESCOLHENDO_SUGESTAO = 5

OPCOES_POR_PAGINA = 3

DIAS_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
DIAS_FIM_DE_SEMANA = ["sabado", "domingo"]
NOMES_DIA_CURTO = {
    "segunda": "Seg", "terca": "Ter", "quarta": "Qua", "quinta": "Qui",
    "sexta": "Sex", "sabado": "Sáb", "domingo": "Dom",
}
BASE_DIR = Path(__file__).resolve().parent
EXEMPLOS_PATH = BASE_DIR / "category_examples.json"
CACHE_EMBEDDINGS_PATH = BASE_DIR / "category_centers.json"
EMBEDDING_MODEL = "gemini-embedding-001"
CACHE_VERSION = 1

with EXEMPLOS_PATH.open("r", encoding="utf-8") as arquivo_exemplos:
    EXEMPLOS_CATEGORIAS = json.load(arquivo_exemplos)

CATEGORIAS = set(EXEMPLOS_CATEGORIAS)
CENTROS_CATEGORIAS = {}


# ===== Classificação por embeddings =====
def assinatura_dos_exemplos():
    conteudo = {
        "cache_version": CACHE_VERSION,
        "model": EMBEDDING_MODEL,
        "examples": EXEMPLOS_CATEGORIAS,
    }
    serializado = json.dumps(
        conteudo,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def gerar_embeddings(textos):
    resultado = gemini_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=textos,
    )
    return np.asarray(
        [embedding.values for embedding in resultado.embeddings],
        dtype=np.float32,
    )


def gerar_embedding(texto):
    return gerar_embeddings([texto])[0]


def normalizar_vetor(vetor):
    norma = np.linalg.norm(vetor)
    return vetor if norma == 0 else vetor / norma


def carregar_centros_do_cache():
    if not CACHE_EMBEDDINGS_PATH.exists():
        return False

    try:
        cache = json.loads(CACHE_EMBEDDINGS_PATH.read_text(encoding="utf-8"))
        if cache.get("examples_hash") != assinatura_dos_exemplos():
            print("Cache de embeddings desatualizado.")
            return False
        if cache.get("model") != EMBEDDING_MODEL:
            return False

        centros = cache.get("centers", {})
        if set(centros) != CATEGORIAS:
            return False

        CENTROS_CATEGORIAS.clear()
        CENTROS_CATEGORIAS.update({
            categoria: normalizar_vetor(np.asarray(vetor, dtype=np.float32))
            for categoria, vetor in centros.items()
        })
        print("Centros das categorias carregados do cache.")
        return True
    except (OSError, ValueError, TypeError) as erro:
        print(f"Não foi possível carregar o cache de embeddings: {erro}")
        return False


def salvar_centros_no_cache():
    cache = {
        "cache_version": CACHE_VERSION,
        "model": EMBEDDING_MODEL,
        "examples_hash": assinatura_dos_exemplos(),
        "centers": {
            categoria: centro.tolist()
            for categoria, centro in CENTROS_CATEGORIAS.items()
        },
    }
    temporario = CACHE_EMBEDDINGS_PATH.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporario.replace(CACHE_EMBEDDINGS_PATH)
    print(f"Cache de embeddings salvo em {CACHE_EMBEDDINGS_PATH.name}.")


def calcular_centros_categorias(forcar=False):
    if not forcar and carregar_centros_do_cache():
        return

    print("Calculando centros das categorias...")
    CENTROS_CATEGORIAS.clear()

    for categoria, exemplos in EXEMPLOS_CATEGORIAS.items():
        embeddings = gerar_embeddings(exemplos)
        centro = normalizar_vetor(np.mean(embeddings, axis=0))
        CENTROS_CATEGORIAS[categoria] = centro

    salvar_centros_no_cache()
    print("Centros calculados com sucesso.")


def cosine_similarity(a, b):
    return float(np.dot(normalizar_vetor(a), normalizar_vetor(b)))


def categorizar(texto_tarefa):
    embedding_tarefa = gerar_embedding(texto_tarefa)
    return max(
        CENTROS_CATEGORIAS,
        key=lambda categoria: cosine_similarity(
            embedding_tarefa,
            CENTROS_CATEGORIAS[categoria],
        ),
    )

# ===== Lógica de sugestão de horário =====
def buscar_rotina_fixa_vigente(data_referencia):
    resultado = supabase.table("rotina_fixa").select("*").execute()
    blocos_validos = []

    for bloco in resultado.data:
        data_inicio = bloco.get("data_inicio")
        data_fim = bloco.get("data_fim")

        if data_inicio and data_referencia < datetime.strptime(data_inicio, "%Y-%m-%d").date():
            continue
        if data_fim and data_referencia > datetime.strptime(data_fim, "%Y-%m-%d").date():
            continue

        blocos_validos.append(bloco)

    return blocos_validos

def buscar_tarefas_agendadas(data_referencia):
    """Busca tarefas pendentes que já têm dia/horário sugerido para essa data."""
    resultado = supabase.table("tarefas") \
        .select("*") \
        .eq("dia_sugerido", data_referencia.isoformat()) \
        .eq("status", "pendente") \
        .execute()
    return resultado.data

def calcular_janelas_livres(dias_a_frente=7):
    janelas_livres = []
    agora = datetime.now()
    hoje = agora.date()

    for i in range(dias_a_frente):
        data_atual = hoje + timedelta(days=i)
        dia_semana_nome = DIAS_SEMANA[data_atual.weekday()]

        if dia_semana_nome in DIAS_FIM_DE_SEMANA:
            inicio_dia = time(9, 0)
        else:
            inicio_dia = time(8, 0)

        fim_dia = time(23, 0)

        if data_atual == hoje:
            hora_atual = agora.time()
            cursor = max(inicio_dia, hora_atual)
        else:
            cursor = inicio_dia

        if cursor >= fim_dia:
            continue

        blocos_do_dia = [
            {"horario_inicio": b["horario_inicio"], "horario_fim": b["horario_fim"]}
            for b in buscar_rotina_fixa_vigente(data_atual)
            if b["dia_semana"] == dia_semana_nome
        ]

        tarefas_do_dia = buscar_tarefas_agendadas(data_atual)
        for tarefa in tarefas_do_dia:
            if not tarefa.get("horario_sugerido") or not tarefa.get("duracao_minutos"):
                continue
            inicio = tarefa["horario_sugerido"]
            duracao = tarefa["duracao_minutos"]
            inicio_dt = datetime.strptime(inicio, "%H:%M:%S")
            fim_dt = inicio_dt + timedelta(minutes=duracao)
            blocos_do_dia.append({
                "horario_inicio": inicio,
                "horario_fim": fim_dt.strftime("%H:%M:%S")
            })

        blocos_do_dia.sort(key=lambda b: b["horario_inicio"])

        for bloco in blocos_do_dia:
            horario_inicio_bloco = datetime.strptime(bloco["horario_inicio"], "%H:%M:%S").time()
            horario_fim_bloco = datetime.strptime(bloco["horario_fim"], "%H:%M:%S").time()

            if horario_fim_bloco <= cursor:
                continue

            if cursor < horario_inicio_bloco:
                janelas_livres.append({
                    "data": data_atual,
                    "dia_semana": dia_semana_nome,
                    "inicio": cursor,
                    "fim": horario_inicio_bloco
                })

            cursor = max(cursor, horario_fim_bloco)

        if cursor < fim_dia:
            janelas_livres.append({
                "data": data_atual,
                "dia_semana": dia_semana_nome,
                "inicio": cursor,
                "fim": fim_dia
            })

    janelas_filtradas = []
    for janela in janelas_livres:
        if janela["dia_semana"] in ["terca", "quinta"]:
            if janela["inicio"] >= time(12, 0) and janela["fim"] <= time(14, 0):
                continue
        janelas_filtradas.append(janela)

    return janelas_filtradas

def duracao_janela_minutos(janela):
    inicio_dt = datetime.combine(janela["data"], janela["inicio"])
    fim_dt = datetime.combine(janela["data"], janela["fim"])
    return (fim_dt - inicio_dt).total_seconds() / 60

def sugerir_horario(duracao_minutos_tarefa):
    janelas = calcular_janelas_livres()
    for janela in janelas:
        if duracao_janela_minutos(janela) >= duracao_minutos_tarefa:
            return janela
    return None


def classificar_faixa_do_dia(horario):
    """Classifica um horário em 'manha' (até 12h), 'tarde' (12h-18h)
    ou 'noite' (a partir de 18h)."""
    if horario < time(12, 0):
        return "manha"
    if horario < time(18, 0):
        return "tarde"
    return "noite"


def candidatos_de_sugestao(duracao_minutos_tarefa):
    """Gera todos os horários de início possíveis dentro das janelas
    livres dos próximos dias, usando o mesmo princípio do fluxo manual:
    o passo entre as opções é igual à própria duração da tarefa (ex:
    tarefa de 1h -> opções de hora em hora dentro de cada janela)."""
    janelas = calcular_janelas_livres()
    candidatos = []
    passo = timedelta(minutes=duracao_minutos_tarefa)

    for janela in janelas:
        if duracao_janela_minutos(janela) < duracao_minutos_tarefa:
            continue

        cursor_dt = datetime.combine(janela["data"], janela["inicio"])
        fim_janela_dt = datetime.combine(janela["data"], janela["fim"])

        while cursor_dt + passo <= fim_janela_dt:
            horario = cursor_dt.time()
            candidatos.append({
                "data": janela["data"],
                "dia_semana": janela["dia_semana"],
                "horario": horario,
                "faixa": classificar_faixa_do_dia(horario),
            })
            cursor_dt += passo

    return candidatos


def intercalar_por_faixa(todos_candidatos):
    """Reordena os candidatos para intercalar manhã/tarde/noite (1 de cada
    por vez, na ordem manhã -> tarde -> noite), preservando a ordem
    cronológica dentro de cada faixa. Quando uma faixa se esgota, as
    demais continuam intercalando entre si."""
    por_faixa = {"manha": [], "tarde": [], "noite": []}
    for candidato in todos_candidatos:
        por_faixa[candidato["faixa"]].append(candidato)

    intercalados = []
    indices = {"manha": 0, "tarde": 0, "noite": 0}
    total = len(todos_candidatos)

    while len(intercalados) < total:
        for faixa in ("manha", "tarde", "noite"):
            i = indices[faixa]
            if i < len(por_faixa[faixa]):
                intercalados.append(por_faixa[faixa][i])
                indices[faixa] += 1

    return intercalados


def gerar_opcoes_sugestao(duracao_minutos_tarefa, pagina=0):
    """Retorna até OPCOES_POR_PAGINA candidatos de horário para a página
    pedida (pagina=0 é a primeira tela), espalhando manhã/tarde/noite
    sempre que possível, e um booleano indicando se há mais opções
    disponíveis em páginas seguintes."""
    todos_candidatos = candidatos_de_sugestao(duracao_minutos_tarefa)
    intercalados = intercalar_por_faixa(todos_candidatos)

    inicio = pagina * OPCOES_POR_PAGINA
    fim = inicio + OPCOES_POR_PAGINA
    opcoes = intercalados[inicio:fim]
    tem_mais = fim < len(intercalados)

    return opcoes, tem_mais


def dias_com_janela_disponivel(duracao_minutos_tarefa):
    """Retorna a lista de datas (sem repetição, em ordem) que têm pelo menos
    uma janela livre grande o suficiente para a duração informada."""
    janelas = calcular_janelas_livres()
    dias_vistos = []
    dias_unicos = set()

    for janela in janelas:
        if duracao_janela_minutos(janela) < duracao_minutos_tarefa:
            continue
        if janela["data"] not in dias_unicos:
            dias_unicos.add(janela["data"])
            dias_vistos.append((janela["data"], janela["dia_semana"]))

    return dias_vistos


def horarios_disponiveis_no_dia(data_escolhida, duracao_minutos_tarefa):
    """Gera os horários de início possíveis para uma tarefa de uma certa duração,
    dentro das janelas livres de um dia específico. O passo entre as opções é
    igual à própria duração da tarefa (ex: tarefa de 30min -> opções de 30 em 30 min)."""
    janelas_do_dia = [
        janela for janela in calcular_janelas_livres()
        if janela["data"] == data_escolhida
        and duracao_janela_minutos(janela) >= duracao_minutos_tarefa
    ]

    horarios = []
    passo = timedelta(minutes=duracao_minutos_tarefa)

    for janela in janelas_do_dia:
        cursor_dt = datetime.combine(janela["data"], janela["inicio"])
        fim_janela_dt = datetime.combine(janela["data"], janela["fim"])

        while cursor_dt + passo <= fim_janela_dt:
            horarios.append(cursor_dt.time())
            cursor_dt += passo

    return horarios

# ===== Handlers do Telegram =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot conectado! Me manda uma tarefa pra testar.")

async def nova_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    categoria = categorizar(texto)

    context.user_data["descricao"] = texto
    context.user_data["categoria"] = categoria

    teclado = [
        [
            InlineKeyboardButton("15 min", callback_data="15"),
            InlineKeyboardButton("30 min", callback_data="30"),
        ],
        [
            InlineKeyboardButton("1 hora", callback_data="60"),
            InlineKeyboardButton("2h ou mais", callback_data="120"),
        ]
    ]
    await update.message.reply_text(
        f"Categoria: {categoria}\nQuanto tempo isso deve levar?",
        reply_markup=InlineKeyboardMarkup(teclado)
    )
    return AGUARDANDO_DURACAO

async def receber_duracao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    duracao_minutos = int(query.data)
    context.user_data["duracao_minutos"] = duracao_minutos

    teclado = [
        [InlineKeyboardButton("🔮 Sugerir horário", callback_data="modo_sugerir")],
        [InlineKeyboardButton("📅 Eu escolho o horário", callback_data="modo_escolher")],
    ]
    await query.edit_message_text(
        f"Duração: {duracao_minutos} min\nComo você quer definir o horário?",
        reply_markup=InlineKeyboardMarkup(teclado)
    )
    return ESCOLHENDO_MODO_HORARIO


async def salvar_tarefa(context, dia_sugerido, horario_sugerido):
    """Insere a tarefa no Supabase usando os dados acumulados em user_data."""
    descricao = context.user_data.get("descricao")
    categoria = context.user_data.get("categoria")
    duracao_minutos = context.user_data.get("duracao_minutos")

    supabase.table("tarefas").insert({
        "descricao": descricao,
        "categoria": categoria,
        "duracao_minutos": duracao_minutos,
        "status": "pendente",
        "dia_sugerido": dia_sugerido.isoformat() if dia_sugerido else None,
        "horario_sugerido": horario_sugerido.strftime("%H:%M:%S") if horario_sugerido else None
    }).execute()

    return descricao, categoria, duracao_minutos


async def montar_tela_sugestao(query, context, pagina):
    duracao_minutos = context.user_data.get("duracao_minutos")
    opcoes, tem_mais = gerar_opcoes_sugestao(duracao_minutos, pagina)

    context.user_data["pagina_sugestao"] = pagina
    context.user_data["opcoes_sugestao"] = opcoes

    if not opcoes:
        if pagina == 0:
            await query.edit_message_text(
                "Não encontrei nenhuma janela livre nos próximos dias."
            )
            return ConversationHandler.END
        # Não há mais opções novas nessa página; volta para a última válida.
        return await montar_tela_sugestao(query, context, pagina - 1)

    botoes = []
    for indice, opcao in enumerate(opcoes):
        rotulo = (
            f"{NOMES_DIA_CURTO[opcao['dia_semana']]} {opcao['data'].strftime('%d/%m')} "
            f"às {opcao['horario'].strftime('%H:%M')}"
        )
        botoes.append([InlineKeyboardButton(rotulo, callback_data=f"sugestao_{indice}")])

    if tem_mais:
        botoes.append([InlineKeyboardButton("🔄 Mais opções", callback_data="sugestao_mais")])

    await query.edit_message_text(
        "Escolha um dos horários sugeridos:",
        reply_markup=InlineKeyboardMarkup(botoes)
    )
    return ESCOLHENDO_SUGESTAO


async def escolher_modo_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    duracao_minutos = context.user_data.get("duracao_minutos")

    if query.data == "modo_sugerir":
        return await montar_tela_sugestao(query, context, pagina=0)

    # query.data == "modo_escolher"
    dias_disponiveis = dias_com_janela_disponivel(duracao_minutos)

    if not dias_disponiveis:
        await query.edit_message_text(
            "Não encontrei nenhum dia com espaço suficiente para essa duração "
            "nos próximos 7 dias. Tarefa não foi salva."
        )
        return ConversationHandler.END

    botoes = []
    linha = []
    for data_disponivel, dia_semana_nome in dias_disponiveis:
        rotulo = f"{NOMES_DIA_CURTO[dia_semana_nome]} {data_disponivel.strftime('%d/%m')}"
        callback = f"dia_{data_disponivel.isoformat()}"
        linha.append(InlineKeyboardButton(rotulo, callback_data=callback))
        if len(linha) == 2:
            botoes.append(linha)
            linha = []
    if linha:
        botoes.append(linha)

    await query.edit_message_text(
        "Escolha o dia:",
        reply_markup=InlineKeyboardMarkup(botoes)
    )
    return ESCOLHENDO_DIA


async def escolher_sugestao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "sugestao_mais":
        pagina_atual = context.user_data.get("pagina_sugestao", 0)
        return await montar_tela_sugestao(query, context, pagina_atual + 1)

    indice = int(query.data.removeprefix("sugestao_"))
    opcoes = context.user_data.get("opcoes_sugestao", [])
    opcao_escolhida = opcoes[indice]

    descricao, categoria, duracao_minutos = await salvar_tarefa(
        context, opcao_escolhida["data"], opcao_escolhida["horario"]
    )

    await query.edit_message_text(
        f"Tarefa salva: {descricao}\nCategoria: {categoria}\n"
        f"Duração: {duracao_minutos} min\n\n"
        f"Agendada para {opcao_escolhida['dia_semana']} "
        f"({opcao_escolhida['data'].strftime('%d/%m')}) às "
        f"{opcao_escolhida['horario'].strftime('%H:%M')}"
    )
    return ConversationHandler.END


async def escolher_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data_escolhida_str = query.data.removeprefix("dia_")
    data_escolhida = datetime.strptime(data_escolhida_str, "%Y-%m-%d").date()
    context.user_data["dia_escolhido"] = data_escolhida

    duracao_minutos = context.user_data.get("duracao_minutos")
    horarios = horarios_disponiveis_no_dia(data_escolhida, duracao_minutos)

    if not horarios:
        await query.edit_message_text(
            "Esse dia não tem mais espaço suficiente para essa duração. "
            "Tente novamente com /start."
        )
        return ConversationHandler.END

    botoes = []
    linha = []
    for horario in horarios:
        rotulo = horario.strftime("%H:%M")
        callback = f"hora_{rotulo}"
        linha.append(InlineKeyboardButton(rotulo, callback_data=callback))
        if len(linha) == 3:
            botoes.append(linha)
            linha = []
    if linha:
        botoes.append(linha)

    await query.edit_message_text(
        f"Dia escolhido: {data_escolhida.strftime('%d/%m')}\nEscolha o horário:",
        reply_markup=InlineKeyboardMarkup(botoes)
    )
    return ESCOLHENDO_HORARIO


async def escolher_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    horario_str = query.data.removeprefix("hora_")
    horario_escolhido = datetime.strptime(horario_str, "%H:%M").time()
    data_escolhida = context.user_data.get("dia_escolhido")

    descricao, categoria, duracao_minutos = await salvar_tarefa(
        context, data_escolhida, horario_escolhido
    )

    await query.edit_message_text(
        f"Tarefa salva: {descricao}\nCategoria: {categoria}\n"
        f"Duração: {duracao_minutos} min\n\n"
        f"Agendada para {data_escolhida.strftime('%d/%m')} às {horario_escolhido.strftime('%H:%M')}"
    )
    return ConversationHandler.END


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado.")
    return ConversationHandler.END

# ===== Inicialização =====
def main():
    calcular_centros_categorias()

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, nova_tarefa)],
        states={
            AGUARDANDO_DURACAO: [CallbackQueryHandler(receber_duracao)],
            ESCOLHENDO_MODO_HORARIO: [CallbackQueryHandler(escolher_modo_horario)],
            ESCOLHENDO_SUGESTAO: [CallbackQueryHandler(escolher_sugestao)],
            ESCOLHENDO_DIA: [CallbackQueryHandler(escolher_dia)],
            ESCOLHENDO_HORARIO: [CallbackQueryHandler(escolher_horario)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()