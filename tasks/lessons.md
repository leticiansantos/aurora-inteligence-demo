# Lessons

- **Planos organizados por tela/funcionalidade.** A Leticia quer ver, para cada tela, o que existe hoje e o que muda,
  com as decisões pendentes listadas por tela. Avançar passo a passo, uma decisão de cada vez.
- **Marca: demo com empresa fictícia (Aurora Motors / assistente Lumi).** Nada que identifique cliente real em
  arquivos commitados, inclusive nomes de schema, caminhos e docs de planejamento. Decisões de marca são da
  Leticia: perguntar antes de mudar.
- **Autenticação de apps: service principal, nunca PAT.**
- **Validação de UI no navegador: nunca abrir um Chrome separado que exija login no Databricks.** O Chrome
  gerenciado da Leticia é o único com SSO. Validar a UI rodando o app localmente (localhost, backend real via
  profile da CLI) ou usar a janela que já está aberta; a identidade do SP é provada por evidência HTTP/queries.
- **Desenvolvimento local; deploy só quando a Leticia pedir.** Validar mudanças rodando o app em localhost
  contra o backend real (profile `classic-stable-new`); não rodar `deploy.sh` a cada mudança.
