# Genie Agent: Aurora Motors · Mercado automotivo

Agente curado sobre os dados de mercado (Fenabrave + Aurora Motors sintética), usado na tela **Genie** do app.

- **Space id:** `01f1e51fb8bb1e7d93d9f4b25aab7517` (workspace `classic-stable-new`).
- **Tabelas:** `market_share_with_aurora`, `market_share_real`, `market_brand_monthly`, `market_model_monthly`,
  `market_segment_totals` (ver `docs/data-model/market.md`).
- **Configuração versionada:** `scripts/genie/build_space.py` (descrições e sinônimos de colunas, instruções,
  5 perguntas de exemplo, 4 SQLs de exemplo, 5 benchmarks parafraseados). SQL canônico em `scripts/genie/queries.sql`.
- **Criar/atualizar (idempotente):** `scripts/genie/deploy_space.sh --profile classic-stable-new` (imprime o id).
- **Validar:** `python3 scripts/genie/ask_benchmarks.py <space_id>`; evidência em `evidence/genie/benchmark-transcript.md`
  (marcas reais mascaradas com `scripts/genie/mask_brands.py`).

## No app
- Plugin `genie` do AppKit, registrado só quando `DATABRICKS_GENIE_SPACE_ID` existe; alias `market`
  (`/api/genie/market/*`, SSE). Tela `app/client/src/pages/GeniePage.tsx` com `useGenieChat`, perguntas sugeridas e
  "Nova conversa"; a conversa fica na URL (`?conversationId=`).
- **Local:** o plugin é OBO. Fora do Databricks Apps não há token do usuário, então rode com `npm run dev`
  (NODE_ENV=development usa a identidade do profile da CLI). `npm run start` local responde 401.
- **Deploy (follow-up):** recurso `genie_space` com CAN_RUN + env no `resources/app.yml` e user authorization no app;
  ver `scripts/genie/app.genie.hunk.yml`.
