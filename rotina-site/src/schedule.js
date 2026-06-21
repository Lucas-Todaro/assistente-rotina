export function inicioDaSemana(data = new Date()) {
  const inicio = new Date(data)
  const deslocamento = (inicio.getDay() + 6) % 7
  inicio.setDate(inicio.getDate() - deslocamento)
  inicio.setHours(0, 0, 0, 0)
  return inicio
}

export function dataDoDia(inicioSemana, indice) {
  const data = new Date(inicioSemana)
  data.setDate(data.getDate() + indice)
  return data
}

export function formatarDataISO(data) {
  return [
    data.getFullYear(),
    String(data.getMonth() + 1).padStart(2, '0'),
    String(data.getDate()).padStart(2, '0'),
  ].join('-')
}

export function dataEhHoje(data) {
  return formatarDataISO(data) === formatarDataISO(new Date())
}

export function horaParaMinutos(hora) {
  if (!hora) return 0
  const [horas, minutos] = hora.split(':').map(Number)
  return horas * 60 + minutos
}

export function montarBlocosPorDia({
  dias,
  datasDaSemana,
  rotinaFixa,
  tarefas,
}) {
  const blocos = Object.fromEntries(dias.map((dia) => [dia.id, []]))

  dias.forEach((dia, indice) => {
    const dataISO = formatarDataISO(datasDaSemana[indice])

    rotinaFixa
      .filter((item) => {
        if (item.dia_semana !== dia.id) return false
        if (item.data_inicio && dataISO < item.data_inicio) return false
        if (item.data_fim && dataISO > item.data_fim) return false
        return true
      })
      .forEach((item) => {
        blocos[dia.id].push({
          id: `fixo-${item.id}`,
          tipo: 'fixo',
          horario: item.horario_inicio,
          horarioFim: item.horario_fim,
          titulo: item.atividade,
        })
      })
  })

  const indicePorData = new Map(
    datasDaSemana.map((data, indice) => [formatarDataISO(data), indice]),
  )

  tarefas.forEach((item) => {
    const indice = indicePorData.get(item.dia_sugerido)
    if (indice === undefined || !item.horario_sugerido) return

    const dia = dias[indice].id
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
}
