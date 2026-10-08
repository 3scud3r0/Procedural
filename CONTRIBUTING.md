# Contribuir

Use este repositório para o núcleo e arquivos derivados. Preserve interfaces pequenas e documente o contrato de cada gerador, capacidade e backend.

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
ruff check procedural_lab tests scripts examples/custom_generator.py
ruff format --check procedural_lab tests scripts examples/custom_generator.py
```

Não use quantidade de linhas como objetivo técnico. Uma mudança deve resolver um problema, ter evidência de funcionamento e indicar limites relevantes. Não introduza abstrações que não tenham uso real.

Para mudanças que alteram saídas por semente, atualize versões e evidências explicitamente. Para performance, guarde ambiente, método, amostras e hashes; evite alegar ganhos medidos em máquinas diferentes.

`procedural.py` deve funcionar quando copiado sozinho. A plataforma mantém suas funcionalidades adicionais em módulos separados. Não adicione dependências ao núcleo para facilitar uma integração periférica.

Experimentos devem separar treino e avaliação, manter seeds e explicar supervisão. Resultados negativos também são resultados.

Depois de mudanças validadas, `python scripts/package_release.py` reconstrói ZIP, TXT e receipt; confira se arquivos internos, caches e credenciais não entraram no pacote.
