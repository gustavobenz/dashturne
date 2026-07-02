# Dashboard Google Sheets com Streamlit

Dashboard em Streamlit para ler dados de uma planilha Google Sheets e exibir:

- metricas de receita total, ingressos pagos e cortesias;
- grafico de receita por cidade;
- tabela de quantidade de ingressos por cidade (total, pagos e cortesias);
- grafico de receita por metodo de pagamento;
- tabela detalhada;
- filtros na barra lateral (periodo, cidade e metodo de pagamento).

O dashboard so exibe cidades da lista `ALLOWED_CITY_NAMES` em `app.py` (as cidades oficiais da
turne). Linhas cuja cidade nao esta nessa lista, ou onde a cidade nao pode ser identificada, sao
descartadas antes de qualquer metrica, grafico ou tabela.

Um ingresso conta como **pago** (entra em "Ingressos pagos" e nas receitas) quando a linha tem
`status = approved` **e** `valor > 0`. Uma **cortesia** e qualquer linha com `valor = 0`,
independente do status. Linhas com outros status (pendente, cancelado etc.) e valor maior que
zero nao entram em nenhuma metrica de receita/pagos, mas continuam aparecendo na tabela
detalhada.

O app le a aba `Dados` da planilha configurada, valida colunas obrigatorias e usa a Google Sheets API com uma Service Account.

## Stack

- Python
- Streamlit
- Pandas
- Altair (graficos)
- Google Sheets API
- Render Starter

## Estrutura esperada da planilha

A planilha precisa ter uma aba chamada exatamente:

```text
Dados
```

A primeira linha da aba deve conter os cabecalhos. As colunas obrigatorias sao:

```text
data_de_criacao
descricao
valor
```

Colunas opcionais para filtros, se existirem:

```text
item
oferta
metodo_pagamento
cidade
status
```

Observacoes:

- Os nomes das colunas sao normalizados para minusculas.
- A coluna `data_de_criacao` deve conter datas validas. Ela corresponde ao cabecalho `Data de criacao` da planilha.
- A coluna `valor` deve conter numeros, podendo usar formato brasileiro como `1.234,56`.
- A coluna `cidade` **nao** e lida diretamente da planilha: ela e sempre derivada do texto da
  coluna `item`, extraindo tudo que vem depois de `TURNE SEVEN ` (ou `TURNÊ SEVEN `) ate o final
  do texto, e normalizada para um nome canonico da lista `ALLOWED_CITY_NAMES` (em `app.py`).
  Exemplo: `03.01.02.023 ACESSOS EXTRAS - TURNÊ SEVEN SAO PAULO` vira cidade `Sao Paulo`. Se o
  texto extraido nao corresponder a nenhuma cidade conhecida, ou se a coluna `item` nao existir,
  a linha fica sem cidade e e descartada do dashboard.
- Para adicionar uma nova cidade a turne, inclua sua variacao normalizada (sem acento, maiuscula)
  em `ALLOWED_CITY_NAMES` em `app.py`, apontando para o nome que deve aparecer nas telas.
- Uma cortesia e qualquer linha com `valor` igual a `0`, independente do `status`.
- Um ingresso so entra nas metricas/graficos de receita quando `status = approved` **e**
  `valor > 0`.

## Variaveis de ambiente

O app exige estas variaveis de ambiente:

```text
GOOGLE_SERVICE_ACCOUNT_JSON
GOOGLE_SPREADSHEET_ID
GOOGLE_SHEET_NAME
```

`GOOGLE_SERVICE_ACCOUNT_JSON` deve conter o JSON completo da chave da Service Account.

`GOOGLE_SPREADSHEET_ID` deve conter o ID da planilha.

`GOOGLE_SHEET_NAME` define a aba lida pelo app. O padrao e `Dados`, mas esta planilha usa `Sheet1`.

Exemplo de URL:

```text
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
```

Use apenas o trecho `SPREADSHEET_ID`. Neste projeto, o ID configurado e:

```text
1ogY8-8jjibTWu1PKcPyKHofoOEL9Hn4RLJUssG2IXao
```

## Aviso de seguranca

Nunca salve credenciais no codigo.

Nunca publique credenciais no GitHub.

Nunca commite um arquivo `.env` com credenciais.

Nunca commite arquivos de secrets do Streamlit com credenciais.

As credenciais devem ficar apenas em variaveis de ambiente no ambiente local ou no Render.

## Executar localmente

No Windows, dentro da pasta do projeto:

```powershell
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

No Linux ou macOS, se `python` apontar para Python 3:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Antes de iniciar o app, configure as variaveis de ambiente no terminal.

Se voce possui o arquivo local `google-credentials.json` na pasta do projeto, use o script seguro:

```powershell
.\run-local.ps1
```

O script define `GOOGLE_SPREADSHEET_ID` com `1ogY8-8jjibTWu1PKcPyKHofoOEL9Hn4RLJUssG2IXao`, define `GOOGLE_SHEET_NAME` como `Sheet1`, le o conteudo local de `google-credentials.json` e inicia o Streamlit. O arquivo `google-credentials.json` esta no `.gitignore` e nao deve ser commitado.

Exemplo manual no PowerShell:

```powershell
$env:GOOGLE_SPREADSHEET_ID="1ogY8-8jjibTWu1PKcPyKHofoOEL9Hn4RLJUssG2IXao"
$env:GOOGLE_SHEET_NAME="Sheet1"
$env:GOOGLE_SERVICE_ACCOUNT_JSON = Get-Content -Raw .\google-credentials.json
py -m streamlit run app.py
```

## Criar uma Service Account no Google Cloud

1. Acesse o Google Cloud Console.
2. Selecione ou crie um projeto.
3. No menu lateral, va em `IAM e administrador`.
4. Abra `Contas de servico`.
5. Clique em `Criar conta de servico`.
6. Informe um nome, por exemplo `streamlit-sheets-reader`.
7. Clique em `Criar e continuar`.
8. Se nao precisar de permissoes adicionais no projeto, pule a concessao de papeis.
9. Conclua a criacao.
10. Abra a Service Account criada.
11. Va na aba `Chaves`.
12. Clique em `Adicionar chave`.
13. Escolha `Criar nova chave`.
14. Selecione `JSON`.
15. Baixe o arquivo JSON e guarde em local seguro.

O conteudo desse JSON sera usado na variavel `GOOGLE_SERVICE_ACCOUNT_JSON`.

## Ativar a Google Sheets API

1. No Google Cloud Console, selecione o mesmo projeto da Service Account.
2. Abra `APIs e servicos`.
3. Clique em `Biblioteca`.
4. Pesquise por `Google Sheets API`.
5. Abra o resultado `Google Sheets API`.
6. Clique em `Ativar`.
7. Aguarde a ativacao concluir.

Sem essa API ativa, o app nao consegue ler a planilha.

## Compartilhar a planilha com a Service Account

1. Abra o arquivo JSON da Service Account.
2. Localize o campo `client_email`.
3. Copie o email completo, parecido com:

```text
nome-da-conta@nome-do-projeto.iam.gserviceaccount.com
```

4. Abra a planilha no Google Sheets.
5. Clique em `Compartilhar`.
6. Cole o `client_email` como destinatario.
7. Defina permissao de `Leitor`.
8. Desative notificacoes, se desejar.
9. Clique em `Compartilhar`.

Se a planilha nao for compartilhada com esse email, o app recebe erro de acesso negado.

## Conectar o projeto ao GitHub

1. Crie um repositorio no GitHub.
2. No computador, inicialize o controle de versao se ainda nao existir:

```bash
git init
```

3. Adicione um `.gitignore` que nao permita arquivos de credenciais.
4. Adicione os arquivos do projeto:

```bash
git add app.py requirements.txt render.yaml README.md .gitignore
```

5. Crie o primeiro commit:

```bash
git commit -m "Initial dashboard"
```

6. Conecte o remoto do GitHub:

```bash
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
```

7. Envie para o GitHub:

```bash
git push -u origin main
```

Nao envie arquivos com credenciais para o GitHub.

## Configurar variaveis de ambiente no Render

1. Acesse o Render.
2. Abra o servico web do projeto.
3. Va em `Environment`.
4. Adicione a variavel `GOOGLE_SPREADSHEET_ID`.
5. Cole o ID da planilha como valor: `1ogY8-8jjibTWu1PKcPyKHofoOEL9Hn4RLJUssG2IXao`.
6. Adicione a variavel `GOOGLE_SHEET_NAME` com o valor `Sheet1`.
7. Adicione a variavel `GOOGLE_SERVICE_ACCOUNT_JSON`.
8. Cole o JSON completo da Service Account como valor.
9. Salve as alteracoes.
10. Faca um novo deploy para aplicar as variaveis.

O Render deve armazenar esses valores como Environment Variables, nao como arquivos no repositorio.

## Deploy no Render Starter

1. Acesse o Render.
2. Clique em `New`.
3. Escolha `Web Service`.
4. Conecte sua conta do GitHub.
5. Selecione o repositorio do projeto.
6. Configure o ambiente como Python.
7. Escolha o plano `Starter`.
8. Configure o build command:

```text
pip install -r requirements.txt
```

9. Configure o start command exatamente assim:

```text
streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
```

10. Configure as variaveis de ambiente:

```text
GOOGLE_SERVICE_ACCOUNT_JSON
GOOGLE_SPREADSHEET_ID
GOOGLE_SHEET_NAME
```

11. Clique em `Create Web Service`.
12. Aguarde o deploy concluir.
13. Abra a URL publica gerada pelo Render.

## Opcao com render.yaml Blueprint

Este projeto tambem pode ser publicado usando o arquivo `render.yaml` como Blueprint no Render.

Nesse fluxo, o Render le a configuracao do servico, incluindo:

- plano `starter`;
- build command `pip install -r requirements.txt`;
- start command do Streamlit;
- variaveis de ambiente esperadas.

Mesmo usando Blueprint, os valores reais de `GOOGLE_SERVICE_ACCOUNT_JSON` e `GOOGLE_SPREADSHEET_ID` devem ser configurados no Render e nunca commitados.

## Problemas comuns

- Erro de aba inexistente: confirme que a aba se chama exatamente `Dados`.
- Erro de colunas ausentes: confirme os cabecalhos `data_de_criacao`, `descricao`, `valor`.
- Erro de acesso negado: compartilhe a planilha com o `client_email` da Service Account.
- Erro de credenciais invalidas: confira se `GOOGLE_SERVICE_ACCOUNT_JSON` contem o JSON completo e valido.
- App sem dados: confirme que a aba `Dados` tem cabecalho e pelo menos uma linha de dados.
