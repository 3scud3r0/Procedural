# Procedural Lab

**Núcleo procedural independente, linguagem executável e ferramentas para experimentos reproduzíveis.** Este é o repositório de destino de `procedural.py` e dos seus derivados neste projeto.

Plataforma **0.1.0**, núcleo independente **1.0.0**. A plataforma é uma primeira base executável, não uma alegação de maturidade equivalente a anos de manutenção em produção. Não representa nem é endossada por Fabio Akita.

## Começar

Python 3.10+, sem dependências de runtime:

```bash
git clone https://github.com/3scud3r0/Procedural.git
cd Procedural
python -m pip install .
procedural run examples/city/main.proc --seed 42 --output output/city
procedural verify output/city
```

Abra `output/city/scene.png` ou `scene.svg`. O programa gera 24 edifícios, 48 objetos visuais, dados e um manifesto SHA-256. A renderização funciona pela CPU, sem WebGL, com projeção isométrica e cores planas. Não promete equivalência visual com Babylon.js.

O diretório de saída deve ser novo: uma execução não sobrescreve outra. Falhas de execução não publicam resultados parciais.

## Dois modos de programar

### Python completo com o núcleo independente

Copie apenas [procedural.py](procedural.py) para seu projeto. Ele continua idêntico à versão entregue anteriormente: biblioteca padrão, sementes/chaves, ruído, gramáticas, reescrita, restrições e geradores extensíveis.

```python
from procedural import Procedural

engine = Procedural(seed=42)

@engine.generator("character")
def character(ctx, level=1):
    return {"health": ctx.randint(10, 20) * level,
            "class": ctx.choose(["mage", "ranger"])}

print(engine.generate("character", level=3, key="hero"))
```

Esse modo executa Python normal com as permissões do processo. Consulte [docs/CORE.md](docs/CORE.md).

### PCL: sintaxe Python, compilador e máquina virtual próprios

```python
from math import sin

def building(x, height=5):
    box(size=[1.5, height, 1.5], position=[x, height / 2, 0])
    return {"x": x, "height": height}

city = []
for i in range(12):
    append(city, building(i * 2, randint(2, 10)))

print("Objects:", len(city))
emit("city.json", city)
```

PCL suporta funções, recursão, parâmetros, módulos do projeto, listas, dicionários, aritmética, condicionais, loops e APIs procedurais. Compila para bytecode JSON com localização no código e executa sem Python `eval`/`exec`.

**Não é Python completo:** classes, comprehensions, closures, imports arbitrários e exceções no código PCL ainda não são suportados. Recursos ausentes são rejeitados pelo compilador. A especificação documenta diferenças, incluindo funções globais pré-registradas e defaults mutáveis isolados por chamada: [docs/LANGUAGE.md](docs/LANGUAGE.md).

## Ferramentas

```bash
procedural compile examples/city/main.proc --output city.bytecode.json
procedural inspect city.bytecode.json
procedural run examples/city/main.proc --output output/traced --trace
procedural run examples/terrain/main.proc --output output/terrain
procedural run examples/graph/main.proc --output output/graph
procedural run examples/grammar/main.proc --output output/grammar
procedural run examples/algorithms/main.proc --output output/algorithms
```

O runner usa processo separado, orçamento de instruções/tempo e encerramento forçado no limite de relógio. Há limites de chamadas, valores, stdout, objetos e arquivos. **Não configura isolamento de filesystem/rede nem um limite de memória do sistema operacional.** Veja [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Exportar para nove linguagens

```bash
procedural export examples/arithmetic.json --output output/backends
```

Python, JavaScript, TypeScript, C, C++, Rust, Go, Lua e SQL. A entrada é uma **IR aritmética explícita**, com variável `x`, constantes, soma, subtração e multiplicação em float64. Isso não transpila qualquer código Python/PCL. O registro de backends pode ser estendido.

[benchmarks/backend_report.json](benchmarks/backend_report.json) registra 90 comparações, dez entradas por backend. Oito executaram por interpretador/compilador correspondente. SQL foi verificado como expressão `SELECT` em SQLite; a definição de função PostgreSQL ainda não foi validada em PostgreSQL.

## Experimentos observáveis

```bash
procedural experiment communication --seed 42 --rounds 10000 --output communication.json
procedural experiment evolution --seed 42 --generations 100 --output evolution.json
python scripts/experiment_suite.py
```

- **Comunicação:** agentes desenvolvem convenções de símbolos para significados dados pelo ambiente. A implementação mede acerto, matriz de confusão e entropia; avaliação não treina agentes.
- **Evolução:** busca de expressões aritméticas, seleção por erro no treino, elitismo e avaliação separada em valores não usados na seleção.

São tarefas pequenas, com supervisão e espaço de busca definidos. Não demonstram compreensão geral, consciência ou superinteligência. Resultados e limitações: [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md).

## Testes, benchmarks e manutenção

```bash
python -m unittest discover -s tests -v
python -m pip install '.[dev]'
ruff check procedural_lab tests scripts examples/custom_generator.py
ruff format --check procedural_lab tests scripts examples/custom_generator.py
procedural benchmark --repeats 5 --output benchmarks/runtime_report.json
python scripts/validate_backends.py
```

Há 52 testes cobrindo o núcleo, compilação, execução, limites, diagnósticos, módulos, serialização, saída atômica, PNG, CLI e experimentos. As comparações de expressões também cobrem 80 conjuntos de entradas reproduzíveis. CI valida Python 3.10, 3.12 e 3.14 em Linux. Compiladores ausentes são reportados como ausentes na validação de backends.

Benchmarks incluem aquecimento, cinco amostras, memória observada por `tracemalloc`, ambiente e hash do resultado. Tempos não são metas nem comparações entre máquinas. Consulte [benchmarks/runtime_report.json](benchmarks/runtime_report.json).

## Organização

```text
procedural.py                   núcleo independente preservado
procedural_lab/compiler.py      parser AST e compilação
procedural_lab/bytecode.py      IR serializável e validação
procedural_lab/vm.py            execução e capacidades
procedural_lab/project.py       arquivos e módulos virtuais
procedural_lab/runner.py        processo encerrável
procedural_lab/artifacts.py     saída atômica e integridade
procedural_lab/geometry.py      cena, SVG e PNG na CPU
procedural_lab/backends.py      IR aritmética e nove destinos
procedural_lab/experiments/     comunicação e evolução
tests/                         testes de comportamento
scripts/                       validação e distribuição
benchmarks/                    evidências medidas
docs/                          contratos e evolução planejada
```

[Arquitetura](docs/ARCHITECTURE.md) · [Linguagem](docs/LANGUAGE.md) · [Plano de evolução](docs/ROADMAP.md) · [Contribuir](CONTRIBUTING.md).

## Downloads

[procedural.py](https://github.com/3scud3r0/Procedural/raw/refs/heads/main/procedural.py) · [ZIP completo](https://github.com/3scud3r0/Procedural/raw/refs/heads/main/downloads/Procedural_Lab_0.1.0.zip) · [Código consolidado TXT](https://github.com/3scud3r0/Procedural/raw/refs/heads/main/downloads/codigo_completo.txt) · [Prévia PNG](https://github.com/3scud3r0/Procedural/raw/refs/heads/main/downloads/city.png).

`python scripts/package_release.py` reconstrói a distribuição, incluindo fontes, testes, documentação, exemplos e evidências. [downloads/distribution.json](downloads/distribution.json) registra contagens e hashes.
