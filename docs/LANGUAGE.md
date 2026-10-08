# PCL 0.1 — especificação executável

PCL usa o parser `ast` do Python e define sua própria semântica em bytecode. É um subconjunto com sintaxe familiar; não é uma implementação de toda a linguagem Python.

## Programa e valores

Um arquivo `.proc` contém instruções e funções no nível do módulo. Literais: inteiro, float finito, texto UTF-8, booleano, `None`, lista, tupla e dicionário. Há indexação; slices não são suportados. Variáveis são locais à função ou globais ao módulo. Não há closures, `global`, `nonlocal`, classes ou métodos de objetos.

Funções do nível do módulo são pré-registradas antes das instruções. Elas podem chamar outras funções declaradas posteriormente. Definições dentro de funções, loops ou condicionais são rejeitadas. Defaults são literais JSON; tuplas e chaves não textuais nos defaults são rejeitadas para preservar o roundtrip do bytecode. Cada chamada recebe uma cópia de defaults mutáveis. Anotações, quando presentes, não executam código nem fazem verificação de tipos.

## Controle de fluxo

```python
def fib(n):
    a = 0
    b = 1
    for i in range(n):
        next_value = a + b
        a = b
        b = next_value
    return a

i = 0
while i < 10:
    i += 1
    if i == 3:
        continue
    if i == 8:
        break
    print(fib(i))
```

Suporta `if/else`, `while`, `for` com um nome como alvo, `break`, `continue`, `return` e `pass`. Não suporta `else` em loops, comprehensions, unpacking, geradores, async, decorators ou try/except. Loops e chamadas consomem o mesmo orçamento global de instruções.

## Expressões

Operadores: `+ - * / // % **`, sinal unário, `not`, `and`, `or`, comparações simples e `in/not in`. `and/or` têm curto-circuito e retornam valores. Comparações encadeadas devem ser escritas usando `and`. Expressões condicionais `a if condition else b` são suportadas. Atribuição aceita nome ou item; atribuição aumentada aceita nome. Atribuições encadeadas não são suportadas.

Não há f-strings, operações bitwise nem acesso genérico a atributos. Atributos só selecionam exports de módulos. `append(xs, value)` modifica uma lista; `xs.append(value)` é rejeitado. Essa decisão mantém a interface de capacidades explícita.

## Funções e APIs

| Grupo | Funções |
| --- | --- |
| Dados | `len`, `abs`, `min`, `max`, `round`, `int`, `float`, `str`, `bool`, `sum`, `sorted`, `list`, `append`, `range` |
| Aleatoriedade | `random`, `randint`, `uniform`, `choose` |
| Procedural | `noise`, `fbm`, `grammar`, `generate` |
| Geometria | `box`, `sphere`, `line` |
| Saída | `print`, `emit` |

Argumentos posicionais e nomeados são suportados. Não há `*args`, `**kwargs` ou expansão na chamada. `generate` acessa os quatro geradores do núcleo: numbers, grammar, terrain e graph. No PCL, terrain tem limite adicional de 10.000 células e graph de 500 nós.

`box(size=[x,y,z], position=[x,y,z], color="#RRGGBB")` retorna um registro e cria objeto na cena. `sphere(radius=..., ...)` e `line(points, width=..., ...)` também. A cena é um documento; objetos não são classes host com métodos ou acesso a recursos gráficos.

`emit("name.json", value)` exporta JSON, texto ou bytes produzidos por capacidades. Nomes devem ser relativos e únicos. Diretórios e `..` não podem escapar da saída. `scene.json`, `scene.svg`, `scene.png`, `trace.json` e `manifest.json` são nomes usados pelas ferramentas e não devem ser emitidos pelo programa.

## Módulos

`import math` e `from math import sin, pi` acessam a capacidade matemática. `import procedural` expõe `generate`, `noise`, `fbm` e `grammar`; não expõe os construtores Python do núcleo. No modo Python normal, a API completa permanece disponível.

Outros imports devem corresponder a arquivos do projeto. `import helper` acessa `helper.proc` ou `helper.py` (ainda compilado como PCL). Imports relativos e wildcard são rejeitados. Cada módulo tem seus próprios globais e é executado uma única vez por VM. Ciclos de import são diagnosticados. Módulos `math` e `procedural` são reservados.

## Projeto JSON

```json
{
  "schema": "procedural.project/1",
  "seed": 42,
  "entry": "main.proc",
  "files": {
    "main.proc": "from helper import value\nprint(value)",
    "helper.proc": "value=42"
  }
}
```

Limites de entrada: 50 arquivos, 1 MB por arquivo, 2 MB no total. Arquivos locais carregados pela CLI são o entry e módulos irmãos, sem varredura recursiva de repositórios. Projetos JSON podem representar caminhos virtuais como `tools/helpers.proc`.

## Bytecode e diagnósticos

`procedural.bytecode/1` guarda nome do arquivo, SHA-256 da fonte, instruções e funções. Cada instrução contém opcode, argumento, linha e coluna (base 1). A validação rejeita opcodes desconhecidos, jumps inválidos, operandos incompatíveis e defaults não portáveis. A VM também diagnostica underflow; ainda não há verificação estática completa de pilha ou de tipos.

Uma compilação de projeto usa envelope `procedural.compilation/1` com entry e módulos. `compile` produz esse envelope; `inspect` lê e desassembla. O comando `run` executa fontes/projetos, não recebe um envelope de bytecode como projeto. Programas de bytecode podem ser executados pela API `VirtualMachine.execute(Program)`.

Erros têm `code`, `message`, `location` e `frames`. A localização aponta para o arquivo importado quando a falha ocorreu ali. Stdout anterior ao erro permanece no relatório, mas arquivos parciais não são publicados.

## Orçamentos e reprodução

Defaults: 200.000 instruções, 5 segundos cooperativos, 128 frames, 100.000 itens por valor, 4.096 bits por inteiro, 10.000 objetos, 5 MB de artefatos e 100 KB de stdout. `run` usa ainda processo encerrável, com margem de 3 segundos para inicialização/renderização. Limites de coleção não são limite de memória agregado do sistema operacional.

Uma VM executa um único projeto. Para repetir, crie outra VM com mesma semente, fontes e parâmetros. Artefatos e hashes devem reproduzir; métricas de tempo não. PRNG: `procedural.sha256/1`. Operações transcendentais em float podem variar minimamente entre plataformas.
