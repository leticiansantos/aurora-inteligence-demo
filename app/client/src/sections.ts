export interface Section {
  path: string;
  label: string;
  description: string;
}

export const SECTIONS: Section[] = [
  { path: '/mercado', label: 'Visão de Mercado', description: 'Emplacamentos por marca e segmento, com a participação da Aurora Motors.' },
  { path: '/pos-venda', label: 'Pós-venda', description: 'Previsão de demanda de peças e risco de ruptura em cada concessionária.' },
  { path: '/genie', label: 'Genie', description: 'Pergunte sobre o mercado de emplacamentos em linguagem natural e veja o SQL e os dados de cada resposta.' },
];
