import test from 'node:test'
import assert from 'node:assert/strict'
import { dataDoDia, montarBlocosPorDia } from './schedule.js'

const DIAS = [
  { id: 'segunda' },
  { id: 'terca' },
  { id: 'quarta' },
  { id: 'quinta' },
  { id: 'sexta' },
  { id: 'sabado' },
  { id: 'domingo' },
]

function datasDaSemana(ano, mes, dia) {
  const inicio = new Date(ano, mes, dia)
  return DIAS.map((_, indice) => dataDoDia(inicio, indice))
}

const rotinaFixa = [{
  id: 1,
  dia_semana: 'segunda',
  horario_inicio: '08:00:00',
  horario_fim: '12:00:00',
  atividade: 'faculdade',
  data_inicio: null,
  data_fim: null,
}]

const tarefas = [{
  id: 22,
  dia_sugerido: '2026-06-22',
  horario_sugerido: '14:00:00',
  duracao_minutos: 60,
  descricao: 'tarefa da próxima semana',
}]

test('não mistura tarefas de segundas-feiras em semanas diferentes', () => {
  const semanaDe15 = montarBlocosPorDia({
    dias: DIAS,
    datasDaSemana: datasDaSemana(2026, 5, 15),
    rotinaFixa,
    tarefas,
  })
  const semanaDe22 = montarBlocosPorDia({
    dias: DIAS,
    datasDaSemana: datasDaSemana(2026, 5, 22),
    rotinaFixa,
    tarefas,
  })

  assert.deepEqual(
    semanaDe15.segunda.map((bloco) => bloco.tipo),
    ['fixo'],
  )
  assert.deepEqual(
    semanaDe22.segunda.map((bloco) => bloco.tipo),
    ['fixo', 'tarefa'],
  )
  assert.equal(semanaDe22.segunda[1].titulo, 'tarefa da próxima semana')
})

test('respeita o período de vigência da rotina fixa em cada semana', () => {
  const rotinaComInicio = [{
    ...rotinaFixa[0],
    data_inicio: '2026-06-22',
  }]

  const semanaDe15 = montarBlocosPorDia({
    dias: DIAS,
    datasDaSemana: datasDaSemana(2026, 5, 15),
    rotinaFixa: rotinaComInicio,
    tarefas: [],
  })
  const semanaDe22 = montarBlocosPorDia({
    dias: DIAS,
    datasDaSemana: datasDaSemana(2026, 5, 22),
    rotinaFixa: rotinaComInicio,
    tarefas: [],
  })

  assert.equal(semanaDe15.segunda.length, 0)
  assert.equal(semanaDe22.segunda.length, 1)
})
