# Desenvolvimento posterior

Esta lista é trabalho futuro, não funcionalidade entregue nem promessa de prazo.

## 0.1: entregue

Núcleo independente, bytecode, compilador PCL, VM com limites, projetos, módulos, runner em processo separado, CLI, PNG/SVG, nove backends de IR aritmética, experimentos, testes e evidências.

## Consolidar contratos

- Verificação estática de pilha e fluxo do bytecode.
- Tipos e signatures para capacidades; inspeção pública das APIs.
- Testes de propriedades mais extensos, fuzzing do compilador e casos de longa duração.
- Publicação concorrente com lock e durabilidade com fsync quando necessária.
- Planejamento de compatibilidade e migração de schemas.

## Evoluir linguagens

- AST própria, parser desacoplado da versão do Python e informações completas de source map.
- Tipos estáticos opcionais e IR comum com condicionais, loops e funções.
- Importação e exportação entre linguagens com conversões explícitas.
- Ferramentas de editor, depurador, breakpoints e inspeção de memória.

## Escalar execução

- Medir e otimizar busca de padrões/grafos antes de introduzir componentes nativos.
- Cancelamento cooperativo nas capacidades, limites de memória e isolamento do SO para execução remota.
- Cache de compilação baseado em conteúdo e builds reproduzíveis.
- Suite de conformidade para backends, incluindo PostgreSQL real.

## Ecossistema

- Protocolo versionado de extensões, dependências e distribuição.
- Linguagens específicas para geometria, dados, narrativas e programas.
- IDE web neste repositório, sem dependência de WebGL para funcionalidades centrais.
- Mais formatos de exportação e renderizadores desacoplados.

## Pesquisa

- Comunicação composicional, feedback parcial e testes de transferência.
- Evolução com objetivos múltiplos, custo computacional e comparação de métodos.
- Agentes com máquinas de estado e protocolos interoperáveis.

Nenhuma etapa implica surgimento inevitável de AGI/ASI. Cada hipótese precisa de tarefa, baseline e avaliação própria.
