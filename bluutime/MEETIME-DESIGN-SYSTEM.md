# MEETIME Design System - extraido das capturas

Fonte: `meetime.com.br (5).zip`, captura local do dashboard da conta BLU Sales Group em 19/08/2026. Este documento descreve o padrao visual observado nos arquivos salvos do proprio app, principalmente:

- `meetime.com.br/dashboard/include/navbar/meetime-navbar.html`
- `meetime.com.br/dashboard/include/header/meetime-header.html`
- `meetime.com.br/dashboard/mt/app/prospector/lead/leadList.html`
- `meetime.com.br/dashboard/mt/app/prospector/cadence/cadenceManagement.html`
- `meetime.com.br/dashboard/css/app-8c30cfa5f8.css`
- `meetime.com.br/dashboard/css/vendor-76a14c7913.css`
- `app.meetime.com.br/ng/styles-QV2AMCRF.css`

## 1. Duas camadas de produto

### 1.1 App principal - AngularJS + Limitless/Bootstrap

E a camada dominante do dashboard. O padrao visual vem de Bootstrap 3/Limitless:

- navbar horizontal superior, fixa, escura e alta
- logo da Meetime na esquerda
- menus dropdown por modulo: Dashboard, Prospeccao, Ligacoes, WhatsApp, Estatisticas, Relatorios
- breadcrumb abaixo da navbar, em faixa branca/cinza
- conteudo em `page-container > page-content > content-wrapper > content`
- paineis `panel panel-flat`
- tabelas `table table-striped table-fixed`
- botoes Bootstrap (`btn`, `btn-default`, `btn-main`, `btn-xs`)
- labels e badges (`label`, `label-success`, `label--light`, `badge`)

### 1.2 Ilhas novas - Angular moderno

Existem telas novas em `app.meetime.com.br/ng/*`, como `control-panel` e `whatsapp/conversation`. Elas usam Inter e CSS mais moderno, mas aparecem embutidas como iframe dentro do app antigo. Para um MVP que precisa parecer Meetime, a regra e: a casca deve seguir o app principal legado.

## 2. Layout base

### Navbar

Arquivo de referencia: `include/navbar/meetime-navbar.html`.

- Classe base: `navbar navbar-lg navbar-fixed-top navbar-inverse navbar-component`
- Fundo escuro quase preto/esverdeado: `#242826`
- Altura visual aproximada: 54-58px
- Logo: `assets/images/logo-inverse.png`
- Menus sao horizontais, nao sidebar
- Cada modulo e um item com icone a esquerda, texto semibold e caret quando abre dropdown
- Dropdowns usam `dropdown-menu dropdown-content`
- Acoes de suporte e usuario ficam a direita

Menus capturados:

- Dashboard
- Prospeccao
  - Painel
  - Execucao
  - Atividades
  - Cadencias
  - Leads
  - Ajustes
- Ligacoes
  - Painel de Ligacoes
  - Lista de Ligacoes
  - Extrato
  - Ajustes
- WhatsApp
  - Conversas
- Estatisticas
  - Demo e Ligacao
  - Prospeccao
  - Feedback de Oportunidade
- Relatorios, marcado como `NOVO`

### Header e breadcrumb

Arquivo de referencia: `include/header/meetime-header.html`.

- Abaixo da navbar existe `page-header`
- A linha de breadcrumb usa `breadcrumb-line breadcrumb-line-wide`
- Elementos de acao ficam em `breadcrumb-elements`, a direita
- Acoes comuns: `Ligar`, `Demonstrar`, `Usuario`
- O conteudo da pagina nao tem hero; a interface e operacional, densa e orientada a tabela

### Conteudo

Arquivo de referencia: `leadList.html`.

Estrutura observada:

```html
<div class="page-container">
  <div class="page-content">
    <div class="content-wrapper">
      <div class="content">
        <div class="panel panel-flat">...</div>
      </div>
    </div>
  </div>
</div>
```

## 3. Cores

Tokens mais frequentes no CSS legado:

| Uso | Cor |
|---|---|
| Navbar escura / texto forte | `#242826` |
| Texto principal | `#333` |
| Branco de painel | `#fff` |
| Linha/borda | `#ddd`, `#e6e6e6`, `#eee` |
| Fundo suave | `#f5f5f5`, `#fafafa`, `#f7f8fa` |
| Texto secundario | `#777`, `#999` |
| Sucesso/novo | `#00a443`, `#00c850`, `#4caf50` |
| Azul informativo | `#2196f3`, `#1e88e5` |
| Erro/perigo | `#f44336`, `#e72910` |
| Acao/alerta laranja | `#ff5722`, `#ef6c00`, `#d84315` |
| Ciano | `#00bcd4` |
| Roxo pontual | `#5e62ff` |

Observacao: o app usa verde para `Novo` e estados positivos. O laranja nao e cor dominante da interface; aparece como alerta/acao secundaria. O MVP nao deve usar azul-noite, terracota, papel, IBM Plex ou bordas secas do CAPIBLU.

## 4. Tipografia

### App legado

- Fonte herdada do template Bootstrap/Limitless, padrao proximo de `Roboto`, `Helvetica Neue`, Arial, sans-serif
- Tamanho base: 13px
- Titulos de painel: 13-15px, `font-weight: 500/600`
- Tabelas: 12-13px
- Textos secundarios usam `text-muted`, `text-grey`, `text-size-small`

### App novo

- `body{font-family:Inter,sans-serif}`
- Deve ser usado apenas em telas que simulam a ilha nova, nao na casca geral do dashboard.

## 5. Componentes

### Painel

Classe principal: `panel panel-flat`.

Padrao:

- fundo branco
- borda cinza clara
- cabecalho `panel-heading`
- titulo `panel-title`
- acoes a direita em `heading-elements`
- corpo em `panel-body`
- sem cards grandes arredondados
- sombra discreta ou ausente

### Botoes

Padrao Bootstrap:

- `btn btn-default`
- `btn btn-main`
- `btn btn-primary`
- `btn btn-success`
- `btn btn-danger`
- tamanhos `btn-xs`, `btn-sm`

Exemplo capturado:

```html
<button class="btn btn-main btn-xs">
  <i class="fa fa-user-plus position-left"></i>Adicionar
</button>
```

### Inputs e busca

Padrao:

- `form-control`
- busca grande: `input-xlg`
- icone dentro do input com `has-feedback has-feedback-left`
- filtros extras aparecem logo abaixo da busca

### Tabelas

Padrao:

- `table table-striped table-fixed`
- cabecalho cinza muito claro
- colunas com classes Bootstrap (`col-md-*`)
- texto cinza em headers (`text-grey`)
- linhas densas, sem cards individuais
- estados via `label label--light` ou `label label-success`

### Abas

Padrao:

- `nav nav-tabs nav-tabs-bottom mt-tabs nav-tabs-component`
- aba ativa tem badge de contagem com `badge-success`
- usadas para funil/pipeline e filtros por etapa

### Alerts

Padroes observados:

- `alert alert-info alert-styled-left alert-bordered`
- `alert alert-warning alert-header no-border`
- `alert alert-danger alert-header no-border`

## 6. Como adicionar uma tela nova sem quebrar o padrao

Para uma aba nova, como `Procurar GENTE`, seguir estas regras:

1. Colocar no menu superior, dentro de `Prospeccao`, como mais um item de dropdown.
2. Usar icone no mesmo estilo (`fa`, `icon-*`) e label verde `Novo` somente se necessario.
3. Conteudo deve usar `page-container`, `content-wrapper`, `content` e `panel panel-flat`.
4. Busca deve usar `main-search`, `form-control input-xlg` e feedback de icone a esquerda.
5. Resultados devem aparecer em tabela Bootstrap, nao em cards do CAPIBLU.
6. Funcoes CAPIBLU devem ser descritas como recursos operacionais dentro da UI da Meetime:
   - CPF/nome/cidade
   - telefones e WhatsApp
   - vinculos RAIS
   - parentes/socios/conexoes quando aplicavel
   - validacao de telefone pertence ao CPF/CNPJ
   - exportacao para lead/cadencia
7. Evitar qualquer rastro visual CAPIBLU:
   - nao usar fundo papel
   - nao usar azul-noite/terracota
   - nao usar IBM Plex
   - nao usar sidebar lateral
   - nao usar cards grandes arredondados
   - nao usar linguagem visual de dashboard proprio

## 7. Padroes visuais observados nos prints

Os prints anexados refinam a leitura feita pelo ZIP. Eles mostram o produto em uso e deixam claro que a fidelidade depende menos de "Bootstrap generico" e mais de proporcao, respiro e densidade por tipo de tela.

### 7.1 Topbar real

- Altura aproximada: 55-57px.
- Fundo: `#383838` a `#3b3b3b`, mais neutro que azul.
- Logo: circulo verde com simbolo `ee` e texto `meetime` branco.
- Itens principais usam icone branco + texto semibold:
  - Dashboard
  - Prospeccao
  - Ligacoes
  - WhatsApp
  - Estatisticas
  - Relatorios
- `Relatorios` recebe label verde `NOVO`, encostado no topo do item.
- A direita: sino, ajuda, avatar circular verde-claro e nome do usuario (`ADM BLU`) com caret.
- Abaixo da topbar ha uma faixa branca de acoes contextuais, normalmente com `Ligar` e `Usuario` alinhados a direita.

### 7.2 Dashboard / Visao geral

Prints 1 e 2.

- Fundo da pagina: cinza muito claro, quase `#f3f3f3`.
- Conteudo nao fica dentro de panel Bootstrap tradicional; fica em area larga com muito respiro.
- Titulo `Visao geral` com peso alto e cerca de 26-28px.
- Filtros aparecem na mesma linha do titulo, alinhados a direita:
  - periodo com icone azul de calendario
  - cadencias com ponto azul
  - usuarios com ponto azul
  - botao arredondado `Editar metas`, borda verde e texto verde
- Card principal:
  - branco, muito largo, borda quase invisivel
  - altura grande, aproximadamente 500px
  - numero principal muito grande (`3`)
  - grafico de linha/area verde a direita
  - linha da meta cinza clara
  - legenda centralizada abaixo do grafico
- Ranking:
  - tres cards brancos em coluna
  - metricas grandes centralizadas
  - listas pequenas com divisores tracejados
- Insights:
  - graficos horizontais simples
  - barras rosadas para perdas e verde para conversao

### 7.3 Painel de controle diario

Print 3.

- Conteudo aparece em uma folha branca centralizada, com borda cinza clara.
- A folha nao ocupa toda a largura: fica com margem grande a esquerda e a direita.
- Titulo no canto superior esquerdo, subtitulo pequeno abaixo.
- Tabela compacta com grupos de coluna:
  - TIME
  - LEADS
  - ATIVIDADES
- Linha verde horizontal separa header de dados.
- Ha barras/setas de scroll horizontais simuladas quando a tabela ultrapassa a largura.

### 7.4 Atividades e ajustes

Prints 4 e 6.

- Usa layout de duas colunas:
  - menu interno vertical estreito a esquerda
  - folha branca principal a direita
- Menu interno:
  - itens em texto pequeno
  - item ativo com fundo branco e indicador verde
- Tela de atividades:
  - icone circular grande centralizado
  - titulo central (`Pesquisa`)
  - subtitulo pequeno
  - tabela simples com nome, instrucoes e menu de tres pontos
  - botao verde quadrado `+` no header da tabela
- Tela de ajuste de atividades diarias:
  - folha branca com icone central cinza
  - campos inline em linhas horizontais
  - icones pequenos de salvar/reset a direita

### 7.5 Cadencias

Print 5.

- Tambem usa folha branca centralizada com menu interno a esquerda.
- Header com titulo `Cadencias` e descricao.
- Linha de filtros densa:
  - status
  - prioridade
  - foco
  - participantes
  - busca por nome
- Indicador de quantidade com ponto verde.
- Abas:
  - `Padrao` ativa com underline verde
  - `E-mail Automatico` secundaria com badge cinza
- Acoes a direita:
  - `Visualizar leads` desabilitado
  - `Criar cadencia` verde
  - pequeno dropdown
- Tabela muito larga, linhas altas, texto pequeno, pílulas de foco (`Outbound`, `Inbound ativo`) e setas de prioridade.

### 7.6 Ligacoes

Print 7.

- Folha branca larga dentro do fundo cinza.
- Bloco de pesquisa/filtros no topo.
- Legenda colorida logo acima da tabela:
  - Significativa verde
  - Nao significativa roxo/azul
  - Cliente ocupado laranja
  - Sem contato vermelho
  - Nao conectada cinza
- Tabela com colunas `Status`, `Origem`, `Destino`, `Data`, `Duracao`, `Opcoes`.
- Links de destino aparecem em azul.
- Botao de exportar CSV no canto direito.

### 7.7 WhatsApp

Print 8.

- Layout novo, mais arredondado que o app legado.
- Container branco com bordas arredondadas de aproximadamente 8-10px.
- Sidebar esquerda fixa de conversas com titulo `Conversas` e botao de filtro.
- Estado vazio: texto `Nenhuma conversa por aqui ainda`.
- Area principal grande com ilustracao preta central e texto pequeno.
- Faixa inferior com padrao de gotas/folhas cinza claras.

## 8. Checklist para o MVP

- Navbar horizontal escura com logo Meetime
- Breadcrumb abaixo da navbar
- Conteudo em paineis brancos `panel panel-flat`
- Menus e dropdowns no topo, nao sidebar
- Tabelas densas e filtros Bootstrap
- Labels verdes para `Novo` e estados positivos
- `Procurar GENTE` integrada no menu Prospeccao
- CAPIBLU aparece como funcionalidade, nao como marca visual
- Dashboard com card grande de metas, ranking e insights
- Cadencias/Atividades com folha central + menu interno
- Ligacoes com legenda de status e tabela densa
- WhatsApp com sidebar e empty state ilustrado
