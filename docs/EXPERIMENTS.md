# Experimentos: hipóteses e medidas

## Comunicação

Agentes possuem tabelas separadas de codificação e decodificação. Um emissor recebe um significado discreto, transmite um símbolo e o receptor tenta identificar esse significado. O ambiente fornece a resposta correta como feedback. Conexões são bidirecionais; direção é sorteada a cada interação.

Essa supervisão é parte do algoritmo. Não há descoberta espontânea do significado de objetos do mundo. O comportamento emergente possível é o alinhamento de convenções de símbolos entre os agentes.

A avaliação congela os agentes, não aplica aprendizado e usa um fluxo aleatório separado. Reutiliza a mesma bateria reproduzível de pares/significados entre checkpoints para comparação. Mede accuracy, confusion matrix, quantidade de símbolos usados e entropia das mensagens. Não mede consciência, generalização para significados ausentes ou capacidade de resolver outras tarefas.

Semente 42, 12 agentes, 6 significados, 12 símbolos e 10.000 interações: baseline 0,146; avaliação final 1,0 em 1.000 tentativas. Consulte `benchmarks/communication_report.json`. É um resultado nessa configuração; a suíte de múltiplas sementes registra variação.

## Evolução de programas

Indivíduos são ASTs aritméticas com `x`, constantes, soma, subtração e multiplicação. A busca usa mutação, torneio e elitismo. A função de fitness é erro absoluto médio nos valores de treino `-3..3`.

A avaliação final usa valores `-10..-4` e `4..10`. Esses valores não entram em ranking, seleção, mutação ou critério de parada. Uma expressão com erro zero no treino pode falhar no teste. A tarefa quadrática é fornecida pelo ambiente; o sistema não inventa sua própria finalidade.

Semente 42 encontrou erro zero em treino e teste na geração 11. A expressão encontrada é maior que a expressão humana `x*x + 3*x + 2`; encontrar uma solução não implica encontrar o programa mais simples. Veja `benchmarks/evolution_report.json`.

A avaliação interna das ASTs satura intermediários em +/-1.000.000 para conter crescimento. O exportador aritmético usa float64 sem essa saturação; converter uma AST evolutiva para a IR de exportação exige verificar seu domínio numérico. Nenhum método gera backpropagation ou melhoria recursiva geral.

## Reproduzir

```bash
procedural experiment communication --seed 42 --rounds 10000 --output communication.json
procedural experiment evolution --seed 42 --generations 100 --output evolution.json
python scripts/experiment_suite.py
```

`benchmarks/multiseed_report.json` registra sementes 0–7 com os mesmos hiperparâmetros, sem selecionar apenas o melhor resultado.

## Próximos experimentos úteis

1. Comparar comunicação com tabelas fixas sem aprendizado, e com diferentes conectividades.
2. Reduzir feedback, introduzir ruído e reservar combinações de significados para teste.
3. Penalizar comprimento/custo dos programas e testar tarefas menos determinadas pelo espaço de busca.
4. Avaliar transferência para tarefas novas, registrando também execuções que falham.

Esses experimentos ainda não estão implementados. Mais gerações e mais regras não garantem inteligência geral.
