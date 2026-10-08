# procedural.py — núcleo procedural reutilizável

Um arquivo independente, Python 3.10+, somente biblioteca padrão. [Download direto](https://github.com/3scud3r0/Procedural/raw/refs/heads/main/procedural.py).

Copie `procedural.py` para o mesmo diretório de seu programa. O núcleo organiza geração por regras e sementes; você implementa o conhecimento específico do que deseja criar em funções Python. O resultado pode ser uma classe sua, texto, código, dados, áudio em bytes, descrições geométricas ou qualquer outro objeto. Os geradores prontos são exemplos, não um catálogo de todos os domínios.

## Criar e compor geradores

```python
from procedural import Procedural, Artifact

engine = Procedural(seed=42)

@engine.generator("building")
def building(ctx, floors=5):
    return {"floors": floors,
            "height": floors * ctx.uniform(2.8, 3.5),
            "material": ctx.choose(["stone", "wood", "glass"])}

@engine.generator("city")
def city(ctx, count=10):
    return [ctx.generate("building", key=i, floors=ctx.randint(1, 12))
            for i in range(count)]

city = engine.generate("city", key="capital", count=20)
Artifact("city.json", city).save("output")
```

Para integração com a linguagem e cena desta plataforma, veja os exemplos em `examples/city/` e a especificação PCL em [LANGUAGE.md](LANGUAGE.md). A API Python completa do núcleo e as capacidades disponíveis em PCL são interfaces diferentes.

## Sementes, chaves e estado

`Procedural(seed)` aceita inteiro, texto ou bytes. `generate(name, key=..., **params)` deriva um fluxo por nome, chave e tentativa. A mesma implementação, semente, parâmetros e chave reproduz o resultado. Gerar outro domínio, registrar outro gerador ou consumir aleatoriedade no contexto pai não altera o fluxo nomeado.

Use `key=i` para instâncias diferentes. Repetir uma chamada com a mesma chave repete o resultado por projeto; não é uma sequência global que avança. Dentro de um gerador, `ctx.random()`, `randint()`, `uniform()`, `normal()`, `choose()`, `shuffle()` e `sample()` avançam seu fluxo. `ctx.fork("vegetation")` cria um contexto independente, sem consumir o pai. `ctx.data` é um dicionário local vazio em cada contexto; passe dados compartilhados explicitamente nos parâmetros.

As chaves devem ser serializáveis em JSON canônico (dicionários com chaves de texto, listas, textos, números finitos, booleanos e null). A posição dos argumentos não interfere no endereço do fluxo. Parâmetros não são automaticamente parte desse endereço: variar um parâmetro pode manter os mesmos sorteios, útil para comparar variantes. A reprodução exige que seu gerador também seja determinístico: relógio, I/O externo, conjuntos sem ordenação e `random` global podem alterá-la.

O PRNG usa SHA-256 com contador, amostragem inteira sem viés e conversão explícita para 53 bits. Não reproduz o DotNetRandom dos modelos MarkovJunior originais. Ruído usa value noise com interpolação quintic; não é Perlin/Simplex. Funções matemáticas de ponto flutuante como `normal()` podem apresentar diferenças mínimas entre plataformas.

## APIs disponíveis

| API | Finalidade |
| --- | --- |
| `@engine.generator("name")` / `engine.register(name, fn)` | Registrar função `(ctx, **params)`; duplicatas exigem `replace=True` |
| `engine.generate(name, key=..., **params)` | Gerar qualquer objeto com contexto isolado |
| `ctx.generate(...)` | Compor geradores a partir do fluxo atual |
| `ctx.fork(key)` | Separar subsistemas aleatórios |
| `ctx.noise(x, y, ..., key="noise")` | Ruído contínuo 1D–4D em `[-1, 1]`, sem consumo do fluxo |
| `ctx.fbm(x, y, ..., octaves=4, ...)` | Ruído em múltiplas escalas, normalizado |
| `ctx.grammar(rules, start="{start}", ...)` | Expansão de regras textuais com alternativas ponderadas |
| `ctx.rewrite(symbols, rules, strategy="random", ...)` | Reescrita de sequências de símbolos Python |
| `ctx.pipeline(value, stages)` | Transformações `(ctx, value) -> novo valor` |
| `Artifact(name, content, format).save(directory)` | Exportar JSON, texto ou bytes |

`Procedural(builtins=False)` inicia um registro vazio. Os geradores prontos são `numbers`, `grammar`, `terrain` e `graph`. Consulte suas assinaturas no próprio arquivo; `engine.generators` lista os nomes registrados. `graph` produz grafo simples não dirigido, com opção de conectividade; `terrain` retorna matriz de alturas, não uma malha/renderização.

## Restrições e tentativas

```python
values = engine.generate("numbers", count=5, minimum=1, maximum=10,
                         integers=True, key="balanced",
                         constraints=[lambda xs: sum(xs) <= 20], attempts=100)
```

Cada tentativa tem seu próprio fluxo. As restrições recebem o resultado; devem ser funções puras. Se nenhuma tentativa servir, ocorre `ConstraintError`. Erros do gerador ou da restrição são propagados imediatamente; não são disfarçados como tentativas malsucedidas. Este mecanismo é busca por rejeição, não um solucionador universal de restrições.

## Gramáticas, reescrita e código

```python
from procedural import Alternative, RewriteRule

ctx = engine.context.fork("text")
text = ctx.grammar({
    "start": "A {place} contains {thing}.",
    "place": ["forest", "city"],
    "thing": [Alternative("a portal", 1), Alternative("a garden", 3)],
})

code = ctx.grammar({
    "start": "def {name}(x):\n    return x * {factor}\n",
    "name": ["transform", "scale"], "factor": ["2", "3", "5"],
})
Artifact("generated.py", code, "text").save("output")

symbols = ctx.rewrite(["bud", "bud"],
                     [RewriteRule(("bud",), ("leaf", "flower"))])
```

`{{` e `}}` são chaves literais nas gramáticas. Elas não executam o texto produzido. No limite de profundidade, a gramática escolhe alternativas terminais; sem alternativa terminal, falha. `max_depth`, `max_expansions`, `max_chars`, `max_steps` e `max_symbols` limitam o trabalho, com `GenerationLimitError` em caso de excesso.

Reescrita aplica um match por passo. `first` respeita a ordem das regras e posições; `random` sorteia entre os matches usando o peso de cada regra (uma regra com muitos matches ganha mais oportunidades). A substituição também pode ser uma função `(ctx, matched_tuple) -> iterable`. Não é uma implementação completa de todos os nós XML do MarkovJunior; o motor original continua em `markovjunior/`.

Para gerar outras linguagens, adapte regras/modelos à sintaxe desejada e valide com seu parser ou compilador. O núcleo não promete compilar ou validar automaticamente qualquer código produzido.

## Executar e testar

```bash
python procedural.py --seed 42 --output output/demo.json
python -m unittest discover -s tests -p test_core.py -v
```

Os testes verificam execução isolada de uma cópia do arquivo, determinismo entre processos, novos domínios, composição, restrições, limites de gramáticas e reescrita, continuidade do ruído, bordas de terrenos, grafos e exportação. O núcleo roda funções Python normais: os limites de gramática/reescrita não limitam o tempo de execução de funções arbitrárias. Na plataforma, a VM e o processo encerrável são responsáveis pelos orçamentos de execução. Esses limites não se aplicam a scripts Python que importam o núcleo diretamente.
