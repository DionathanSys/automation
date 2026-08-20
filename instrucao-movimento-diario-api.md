# Instrucao: endpoint para Movimento Diario (Sascar)

Este documento instrui a **aplicacao receptor (sistema Magnabosco)** a criar um ponto de API para receber os dados do relatorio "Movimento Diario" extraido do portal Sascar Telemetria.

O scraper (aplicacao WebScraping) le o relatorio por veiculo e envia os dados nesta API.

## 1. Origem dos dados

Portal: https://telemetria.sascar.com.br/telemetria/pages/controller.jsf
Relatorio: "Daily movement" (Movimento Diario), filial de veiculos = Chapeco.

### Periodo: ultimas 4 horas (fuso -3)

O scraper sempre gera o relatorio para a janela das **ultimas 4 horas em relacao ao horario atual no fuso -3 (Brasilia)**:

```text
inicio = agora_utc_minus3 - 4 horas
fim    = agora_utc_minus3
```

- Os campos de data do portal usam a mascara `dd/mm/yyyy hh:mm` (segundos sao desprezados).
- O relatorio renderiza colunas para todas as 24 horas (0h a 23h), mas **somente as horas que intersectam a janela [inicio, fim] contem dados reais**; as demais colunas exibem valores de preenchimento sem significado. Por isso o scraper envia **apenas as horas dentro da janela**.
- Se a janela cruzar a meia-noite, o relatorio pode trazer **mais de um dia** (uma linha por dia). Nesse caso o scraper envia **uma requisicao por dia**.

O relatorio e gerado **por veiculo** (uma geracao por placa). Cada relatorio traz:

- Uma linha por dia, com a distancia total e o tempo de movimento do dia.
- Para cada hora do dia (0h a 23h), **6 quadrados** de status.
- Legenda do relatorio (3 status possiveis):

| Codigo | Cor/Icone no relatorio | Significado |
|--------|------------------------|-------------|
| `0`    | `vei_mov.gif`          | Em movimento |
| `1`    | `vei_par_lig.gif`      | Parado com motor ligado |
| `2`    | `vei_des.gif`          | Veiculo desligado |

Na pagina, cada quadrado e um elemento `<div class="minuto_0|1|2">` dentro da coluna da hora. O primeiro quadrado da hora equivale aos primeiros 10 minutos, e assim por diante (6 quadrados = 60 minutos).

## 2. Base URL

Substituir pelo dominio do ambiente receptor:

```text
https://seu-dominio.com
```

## 3. Autenticacao por assinatura

Mesma regra dos demais endpoints do contrato: HMAC SHA-256.

### Headers obrigatorios

```http
Content-Type: application/json
X-Webhook-Timestamp: <unix timestamp em segundos>
X-Webhook-Signature: sha256=<assinatura>
```

Header recomendado para debug:

```http
X-Request-Id: <uuid ou identificador unico da requisicao>
```

### Como gerar a assinatura

```text
<timestamp>.<body-json-bruto>
```

Exemplo em PHP:

```php
$timestamp = time();
$rawBody = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
$signature = 'sha256='.hash_hmac('sha256', $timestamp.'.'.$rawBody, $secret);
```

O `rawBody` usado na assinatura deve ser exatamente o mesmo JSON enviado no corpo da requisicao.

## 4. Endpoint

```http
POST /api/integracoes/movimento-diario
```

Enviar **uma requisicao por veiculo e por dia** (uma placa e um dia por chamada). Quando a assinatura e o payload forem validos, a API retorna `200` e enfileira o processamento.

### Payload

```json
{
  "lote_id": "sascar-movimento-diario-20260811-001",
  "veiculo": "RLE7C85",
  "filial": "MAGNABOSCO - CHAPECÓ",
  "inicio": "2026-08-11 15:47:00",
  "fim": "2026-08-11 19:47:00",
  "dia": "2026-08-11",
  "km": 63.9,
  "tempo_movimento": "03:07:57",
  "horas": [
    { "hora": 15, "minutos": ["0", "0", "0", "0", "2", "2"] },
    { "hora": 16, "minutos": ["0", "0", "1", "1", "1", "1"] },
    { "hora": 17, "minutos": ["1", "1", "2", "2", "2", "2"] },
    { "hora": 18, "minutos": ["0", "1", "1", "1", "1", "1"] },
    { "hora": 19, "minutos": ["0", "0", "0", "0", "0", "0"] }
  ]
}
```

### Significado dos campos

| Campo | Tipo | Obrigatorio | Descricao |
|-------|------|-------------|-----------|
| `lote_id` | string | sim | Identificador do lote de scraping (data/hora da extracao). |
| `veiculo` | string | sim | Placa do veiculo. |
| `filial` | string | sim | Filial de veiculos selecionada no relatorio. |
| `inicio` | string | sim | Inicio da janela consultada no formato `YYYY-MM-DD HH:MM:SS`, fuso -3. |
| `fim` | string | sim | Fim da janela consultada no formato `YYYY-MM-DD HH:MM:SS`, fuso -3. |
| `dia` | string | sim | Data da linha do relatorio no formato `YYYY-MM-DD`. |
| `km` | float | sim | Distancia total percorrida no dia (coluna Km do relatorio). |
| `tempo_movimento` | string | sim | Tempo total em movimento no dia no formato `HH:MM:SS` (coluna Tempo do relatorio). |
| `horas` | array | sim | Apenas as horas que intersectam a janela `[inicio, fim]`. |
| `horas[].hora` | int | sim | Hora do dia (0-23). |
| `horas[].minutos` | array | sim | 6 valores de status, um por quadrado (cada um representa 10 minutos da hora). Valores validos: `0`, `1` ou `2`. |

### Aliases aceitos

- `placa` no lugar de `veiculo`.
- `data` no lugar de `dia`.
- `tempo` no lugar de `tempo_movimento`.
- `veiculo_id`, caso o scraper repasse o ID interno da Sascar (recomendado apenas como referencia, nunca como identificador unico).

### Codigo de status

| Valor | Status |
|-------|--------|
| `0` | Em movimento |
| `1` | Parado com motor ligado |
| `2` | Veiculo desligado |

### Regras de processamento sugeridas

- Usar a chave `(veiculo, dia)` como identificador unico do registro.
- Se `(veiculo, dia)` ja existir, o registro deve ser **substituido** (a extracao refaz a janela a cada execucao e o dia inteiro e reenviado).
- Validar que cada `minutos` tenha exatamente 6 valores dentro de `0|1|2`; caso contrario, rejeitar com `422`.
- As horas fora da janela `[inicio, fim]` nao sao enviadas e nao devem ser consideradas.
- Falhas no processamento assincrono devem ser agrupadas e notificadas por e-mail pelo sistema receptor.

## 5. Resposta de sucesso

Status: `200`

```json
{
  "success": true,
  "message": "Movimento diario recebido e enfileirado para processamento.",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "lote_id": "sascar-movimento-diario-20260811-001",
  "veiculo_key": "placa:RLE7C85"
}
```

## 6. Respostas de erro comuns

### Assinatura invalida

Status: `401`

```json
{
  "message": "Invalid signature."
}
```

### Payload invalido

Status: `422`

```json
{
  "success": false,
  "message": "Payload invalido.",
  "errors": {
    "horas.0.minutos": [
      "The horas.0.minutos must contain exactly 6 items."
    ]
  }
}
```

### Integracao nao configurada no receptor

Status: `503`

```json
{
  "message": "Integration not configured."
}
```

## 7. Exemplo cURL

```bash
timestamp=$(date +%s)
body='{"lote_id":"sascar-movimento-diario-20260811-001","veiculo":"RLE7C85","filial":"MAGNABOSCO - CHAPECÓ","inicio":"2026-08-11 15:47:00","fim":"2026-08-11 19:47:00","dia":"2026-08-11","km":63.9,"tempo_movimento":"03:07:57","horas":[{"hora":15,"minutos":["0","0","0","0","2","2"]},{"hora":16,"minutos":["0","0","1","1","1","1"]},{"hora":17,"minutos":["1","1","2","2","2","2"]},{"hora":18,"minutos":["0","1","1","1","1","1"]},{"hora":19,"minutos":["0","0","0","0","0","0"]}]}'
signature="sha256=$(printf "%s.%s" "$timestamp" "$body" | openssl dgst -sha256 -hmac "$WEBSCRAPER_API_SECRET" -binary | xxd -p -c 256)"

curl -X POST "https://seu-dominio.com/api/integracoes/movimento-diario" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Timestamp: $timestamp" \
  -H "X-Webhook-Signature: $signature" \
  -H "X-Request-Id: 550e8400-e29b-41d4-a716-446655440000" \
  -d "$body"
```

## 8. Notas para o scraper (apenas contexto, nao e contrato)

- Periodo usado no portal: "Date Range" (perido 5), com inicio = agora - 4h e fim = agora, ambos em fuso -3 (UTC-3).
- O relatorio e aberto em uma janela popup ("Pop-up" em Forma de Visualizacao).
- A tabela tem o cabecalho: `Date | Km | Time | 0 | 01 | 02 | ... | 23` (as 24 colunas de hora sempre aparecem, mas apenas as horas dentro da janela tem dados reais).
- Cada coluna de hora contem 6 elementos `<div class="minuto_0|1|2">`.
- E necessario gerar um relatorio por veiculo da filial Chapeco (lista do campo Veiculo apos selecionar a filial).
