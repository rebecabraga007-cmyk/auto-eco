# Modelo de dossiê com web search

Arquivo de referência visual: `modelo-dossie-websearch.pdf`.

Este modelo foi definido a partir do último PDF revisado manualmente:
`dossie-simone-claude-com-processos-insight-web.pdf`.

## Regras de geração

- Manter a estrutura principal do dossiê atual: capa, dados cadastrais, contatos, endereços, vínculos, telefones confirmados, certidão de antecedentes quando disponível, insight IA e anexos/dados brutos quando aplicável.
- Preservar o texto do insight original da pessoa principal quando a pesquisa web encontrar apenas informações de familiares.
- Adicionar os achados web como complemento contextual, sem transformar informações de parentes em conclusão direta sobre a pessoa consultada.
- Incluir uma seção dedicada a processos judiciais e registros públicos correlatos quando houver achados web.
- Identificar fonte, data de consulta, termo pesquisado, nomes relacionados e grau de confiança do vínculo.
- Declarar quando a busca web não encontrou correspondências relevantes; isso não equivale a certidão negativa.
- Corrigir encoding de acentos no PDF. Nunca substituir caracteres acentuados por `?`.
- Usar fontes Unicode/TrueType quando disponíveis para evitar perda de acentos no ReportLab.

## Seção de processos e registros públicos

Título sugerido:
`Processos judiciais e registros públicos correlatos`

Campos esperados por achado:

- Pessoa ou termo pesquisado
- Relação com a pessoa principal
- Fonte consultada
- Resultado encontrado
- Link ou identificador público, quando disponível
- Observação de cautela sobre homônimos ou vínculo indireto

## Insight IA

O Mistral deve receber o conteúdo de `agente.md` como instrução complementar sempre que o dossiê tiver achados web. A resposta continua no formato esperado pelo PDF:

```text
RESUMO: <texto>
PERFIL: <texto>
```

O campo `PERFIL` pode conter a leitura complementar dos achados web, desde que mantenha o aviso de inferência e não afirme fatos não sustentados pelas fontes.
