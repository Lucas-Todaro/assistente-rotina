import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { supabase } from './supabaseClient'
import './App.css'

const DIAS = [
  { id: 'segunda', curto: 'seg', nome: 'segunda-feira' },
  { id: 'terca', curto: 'ter', nome: 'terça-feira' },
  { id: 'quarta', curto: 'qua', nome: 'quarta-feira' },
  { id: 'quinta', curto: 'qui', nome: 'quinta-feira' },
  { id: 'sexta', curto: 'sex', nome: 'sexta-feira' },
  { id: 'sabado', curto: 'sáb', nome: 'sábado' },
  { id: 'domingo', curto: 'dom', nome: 'domingo' },
]

function diaSemanaDeHoje() {
  const indice = (new Date().getDay() + 6) % 7
  return DIAS[indice].id
}

function inicioDaSemana(data = new Date()) {
  const inicio = new Date(data)
  const deslocamento = (inicio.getDay() + 6) % 7
  inicio.setDate(inicio.getDate() - deslocamento)
  inicio.setHours(0, 0, 0, 0)
  return inicio
}

function dataDoDia(indice) {
  const data = inicioDaSemana()
  data.setDate(data.getDate() + indice)
  return data
}

function formatarHora(hora) {
  return hora ? hora.slice(0, 5) : ''
}

function horaParaMinutos(hora) {
  if (!hora) return 0
  const [horas, minutos] = hora.split(':').map(Number)
  return horas * 60 + minutos
}

function minutosDoBloco(bloco) {
  const inicio = horaParaMinutos(bloco.horario)
  const fim = horaParaMinutos(bloco.horarioFim)
  return Math.max(fim - inicio, bloco.duracaoMinutos || 30)
}

function formatarDuracao(minutos) {
  if (minutos < 60) return `${minutos} min`
  const horas = Math.floor(minutos / 60)
  const restante = minutos % 60
  return restante ? `${horas}h ${restante}min` : `${horas}h`
}

function alturaVisualDaDuracao(minutos, contexto = 'desktop') {
  const configuracao = contexto === 'mobile'
    ? { base: 62, escala: 0.43, minimo: 92, maximo: 230 }
    : { base: 52, escala: 0.5, minimo: 76, maximo: 244 }

  return Math.round(
    Math.min(
      configuracao.maximo,
      Math.max(configuracao.minimo, configuracao.base + minutos * configuracao.escala),
    ),
  )
}

function formatarIntervaloSemana() {
  const inicio = dataDoDia(0)
  const fim = dataDoDia(6)
  const mesInicio = inicio
    .toLocaleDateString('pt-BR', { month: 'short' })
    .replace('.', '')
  const mesFim = fim
    .toLocaleDateString('pt-BR', { month: 'short' })
    .replace('.', '')

  if (inicio.getMonth() === fim.getMonth()) {
    return `${String(inicio.getDate()).padStart(2, '0')} — ${String(fim.getDate()).padStart(2, '0')} ${mesFim} ${fim.getFullYear()}`
  }

  return `${String(inicio.getDate()).padStart(2, '0')} ${mesInicio} — ${String(fim.getDate()).padStart(2, '0')} ${mesFim} ${fim.getFullYear()}`
}

function Marca() {
  return (
    <div className="brand" aria-label="Rotina de estudos">
      <span className="brand__text">rotina</span>
      <span className="brand__tag">estudos</span>
    </div>
  )
}

function IconeRelogio() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5v5l3.25 2" />
    </svg>
  )
}

function IconeCalendario() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5.5" width="16" height="14" rx="2.5" />
      <path d="M8 3.5v4M16 3.5v4M4 9.5h16" />
    </svg>
  )
}

function SeletorDeDias({ diaAtivo, aoSelecionar, blocosPorDia }) {
  const referenciaAtiva = useRef(null)

  useEffect(() => {
    const movimentoReduzido = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    referenciaAtiva.current?.scrollIntoView({
      behavior: movimentoReduzido ? 'auto' : 'smooth',
      block: 'nearest',
      inline: 'center',
    })
  }, [diaAtivo])

  const hoje = diaSemanaDeHoje()

  return (
    <nav className="day-selector" aria-label="Selecionar dia da semana">
      {DIAS.map((dia, indice) => {
        const ativo = dia.id === diaAtivo
        const atual = dia.id === hoje
        const quantidade = blocosPorDia[dia.id]?.length || 0

        return (
          <button
            className={`day-tab${ativo ? ' is-active' : ''}${atual ? ' is-today' : ''}`}
            key={dia.id}
            type="button"
            onClick={() => aoSelecionar(dia.id)}
            aria-pressed={ativo}
            aria-current={atual ? 'date' : undefined}
            ref={ativo ? referenciaAtiva : null}
          >
            <span className="day-tab__weekday">{dia.curto}</span>
            <span className="day-tab__date">{String(dataDoDia(indice).getDate()).padStart(2, '0')}</span>
            <span className="day-tab__meta">
              <span className="day-tab__dot" />
              {quantidade}
            </span>
          </button>
        )
      })}
    </nav>
  )
}

function ItemDaSemana({ bloco }) {
  const duracao = minutosDoBloco(bloco)

  return (
    <article
      className={`week-entry week-entry--${bloco.tipo}`}
      style={{ '--entry-height': `${alturaVisualDaDuracao(duracao)}px` }}
    >
      <div className="week-entry__time">
        <strong>{formatarHora(bloco.horario)}</strong>
        <span>{formatarHora(bloco.horarioFim)}</span>
      </div>
      <div className="week-entry__content">
        <h3>{bloco.titulo}</h3>
        <span>
          {bloco.tipo === 'fixo' ? 'rotina fixa' : 'tarefa'} · {formatarDuracao(duracao)}
        </span>
      </div>
    </article>
  )
}

function VisaoSemanal({ blocosPorDia }) {
  const hoje = diaSemanaDeHoje()

  return (
    <div className="weekly-board">
      {DIAS.map((dia, indice) => {
        const blocos = blocosPorDia[dia.id]
        const atual = dia.id === hoje

        return (
          <section className={`week-day${atual ? ' is-today' : ''}`} key={dia.id}>
            <header className="week-day__header">
              <div>
                <span>{dia.curto}</span>
                {atual && <em>Hoje</em>}
              </div>
              <strong>{String(dataDoDia(indice).getDate()).padStart(2, '0')}</strong>
            </header>

            <div className="week-day__list">
              {blocos.length ? (
                blocos.map((bloco) => <ItemDaSemana bloco={bloco} key={bloco.id} />)
              ) : (
                <p className="week-day__empty">Nenhum bloco</p>
              )}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function AgendaDoDia({ dia, blocos }) {
  const infoDia = DIAS.find((item) => item.id === dia)
  const indiceDia = DIAS.findIndex((item) => item.id === dia)
  const data = dataDoDia(indiceDia)
  const totalMinutos = blocos.reduce((total, bloco) => total + minutosDoBloco(bloco), 0)

  return (
    <section className="mobile-agenda" aria-labelledby="agenda-heading">
      <header className="agenda-heading">
        <div>
          <span className="eyebrow">agenda do dia</span>
          <h2 id="agenda-heading">{infoDia.nome}</h2>
          <p>
            {data.toLocaleDateString('pt-BR', {
              day: '2-digit',
              month: 'long',
              year: 'numeric',
            })}
          </p>
        </div>
        <div className="agenda-heading__summary">
          <strong>{blocos.length}</strong>
          <span>{blocos.length === 1 ? 'bloco' : 'blocos'}</span>
        </div>
      </header>

      {blocos.length ? (
        <>
          <div className="agenda-duration">
            <IconeRelogio />
            <span>{formatarDuracao(totalMinutos)} planejados</span>
          </div>

          <ol className="agenda-list">
            {blocos.map((bloco, indice) => (
              <li
                className={`agenda-item agenda-item--${bloco.tipo}`}
                key={bloco.id}
                style={{
                  '--item-index': indice,
                  '--agenda-height': `${alturaVisualDaDuracao(minutosDoBloco(bloco), 'mobile')}px`,
                }}
              >
                <div className="agenda-item__time">
                  <strong>{formatarHora(bloco.horario)}</strong>
                  <span>{formatarHora(bloco.horarioFim)}</span>
                </div>
                <span className="agenda-item__rail" aria-hidden="true">
                  <span />
                </span>
                <article className="agenda-card">
                  <div className="agenda-card__topline">
                    <span className="agenda-card__type">
                      {bloco.tipo === 'fixo' ? 'rotina fixa' : 'tarefa'}
                    </span>
                    <span>{formatarDuracao(minutosDoBloco(bloco))}</span>
                  </div>
                  <h3>{bloco.titulo}</h3>
                </article>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <div className="empty-state">
          <span className="empty-state__icon" aria-hidden="true">
            <IconeCalendario />
          </span>
          <h3>Dia livre por enquanto</h3>
          <p>Nenhum bloco foi programado para este dia.</p>
        </div>
      )}
    </section>
  )
}

function EstadoCarregando() {
  return (
    <div className="loading-state" aria-live="polite">
      <span className="loading-state__label">organizando sua semana</span>
      <div className="loading-state__bar">
        <span />
      </div>
    </div>
  )
}

export default function App() {
  const [diaAtivo, setDiaAtivo] = useState(diaSemanaDeHoje())
  const [rotinaFixa, setRotinaFixa] = useState([])
  const [tarefas, setTarefas] = useState([])
  const [carregando, setCarregando] = useState(true)

  const carregarDados = useCallback(async () => {
    const hoje = new Date().toISOString().split('T')[0]

    const [{ data: rotina }, { data: tarefasData }] = await Promise.all([
      supabase
        .from('rotina_fixa')
        .select('*')
        .or(`data_inicio.is.null,data_inicio.lte.${hoje}`)
        .or(`data_fim.is.null,data_fim.gte.${hoje}`),
      supabase
        .from('tarefas')
        .select('*')
        .eq('status', 'pendente')
        .not('dia_sugerido', 'is', null),
    ])

    setRotinaFixa(rotina || [])
    setTarefas(tarefasData || [])
    setCarregando(false)
  }, [])

  useEffect(() => {
    const carregamentoInicial = window.setTimeout(carregarDados, 0)

    const canalRotina = supabase
      .channel('rotina_fixa_changes')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'rotina_fixa' }, carregarDados)
      .subscribe()

    const canalTarefas = supabase
      .channel('tarefas_changes')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'tarefas' }, carregarDados)
      .subscribe()

    return () => {
      window.clearTimeout(carregamentoInicial)
      supabase.removeChannel(canalRotina)
      supabase.removeChannel(canalTarefas)
    }
  }, [carregarDados])

  const blocosPorDia = useMemo(() => {
    const blocos = Object.fromEntries(DIAS.map((dia) => [dia.id, []]))

    rotinaFixa.forEach((item) => {
      if (!blocos[item.dia_semana]) return
      blocos[item.dia_semana].push({
        id: `fixo-${item.id}`,
        tipo: 'fixo',
        horario: item.horario_inicio,
        horarioFim: item.horario_fim,
        titulo: item.atividade,
      })
    })

    tarefas.forEach((item) => {
      const dataTarefa = new Date(`${item.dia_sugerido}T00:00:00`)
      const dia = DIAS[(dataTarefa.getDay() + 6) % 7]?.id
      if (!dia) return

      const inicioMin = horaParaMinutos(item.horario_sugerido)
      const fimMin = inicioMin + (item.duracao_minutos || 30)
      const horarioFim = `${String(Math.floor(fimMin / 60)).padStart(2, '0')}:${String(fimMin % 60).padStart(2, '0')}:00`

      blocos[dia].push({
        id: `tarefa-${item.id}`,
        tipo: 'tarefa',
        horario: item.horario_sugerido,
        horarioFim,
        duracaoMinutos: item.duracao_minutos,
        titulo: item.descricao,
      })
    })

    Object.values(blocos).forEach((lista) => {
      lista.sort((a, b) => horaParaMinutos(a.horario) - horaParaMinutos(b.horario))
    })

    return blocos
  }, [rotinaFixa, tarefas])

  const todosOsBlocos = Object.values(blocosPorDia).flat()
  const totalMinutos = todosOsBlocos.reduce(
    (total, bloco) => total + minutosDoBloco(bloco),
    0,
  )

  return (
    <div className="app-shell">
      <header className="topbar">
        <Marca />
        <div className={`sync-status${carregando ? ' is-loading' : ''}`}>
          <span aria-hidden="true" />
          {carregando ? 'sincronizando' : 'atualizado'}
        </div>
      </header>

      <main className="workspace">
        <section className="planner" aria-label="Planejamento semanal">
          <header className="planner-panel__header">
            <div>
              <span className="eyebrow">semana atual</span>
              <h1>planejamento semanal</h1>
            </div>

            <div className="planner-panel__info">
              <dl className="week-summary">
                <div>
                  <dt>semana</dt>
                  <dd>{formatarIntervaloSemana()}</dd>
                </div>
                <div>
                  <dt>blocos</dt>
                  <dd>{String(todosOsBlocos.length).padStart(2, '0')}</dd>
                </div>
                <div>
                  <dt>tempo</dt>
                  <dd>{formatarDuracao(totalMinutos)}</dd>
                </div>
              </dl>

              <div className="legend" aria-label="Legenda">
                <span><i className="is-fixed" />Rotina fixa</span>
                <span><i className="is-task" />Tarefa</span>
              </div>
            </div>
          </header>

          {carregando ? (
            <EstadoCarregando />
          ) : (
            <>
              <div className="mobile-view">
                <SeletorDeDias
                  aoSelecionar={setDiaAtivo}
                  blocosPorDia={blocosPorDia}
                  diaAtivo={diaAtivo}
                />
                <AgendaDoDia blocos={blocosPorDia[diaAtivo]} dia={diaAtivo} />
              </div>
              <VisaoSemanal blocosPorDia={blocosPorDia} />
            </>
          )}
        </section>
      </main>
    </div>
  )
}
