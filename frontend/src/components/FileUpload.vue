<script setup>
import { ref } from 'vue'
import axios from 'axios'

const emit = defineEmits(['upload-success', 'upload-error'])

const file = ref(null)
const loading = ref(false)
const error = ref('')
const result = ref(null)
const config = ref('')
async function handleFile(event) {
  const selectedFile = event.target.files?.[0]
  if (!selectedFile) return

  if (!selectedFile.name.toLowerCase().endsWith('.csv')) {
    error.value = 'Selecione um arquivo CSV válido.'
    event.target.value = ''
    return
  }

  file.value = selectedFile
  error.value = ''
  result.value = null
  loading.value = true
  config.value = JSON.stringify({
    "fundo": {
      "nome": "ANTECIPE FIDC",
      "cnpj": "92.234.400/0001-80"
    },
    "validadores": [
      {
        "codigo": "CNPJ_SACADO_VALIDO",
        "ativo": true,
        "parametros": {}
      },
      {
        "codigo": "SITUACAO_CADASTRAL_SACADO",
        "ativo": true,
        "parametros": {
          "situacoes_aceitas": [
            "ATIVA"
          ]
        }
      },
      {
        "codigo": "TIPO_RECEBIVEL",
        "ativo": true,
        "parametros": {
          "tipos_aceitos": [
            "Duplicata",
            "Duplicata de Serviço"
          ]
        }
      },
      {
        "codigo": "VALOR_MINIMO",
        "ativo": true,
        "parametros": {
          "valor_minimo": 100.0
        }
      },
      {
        "codigo": "NAO_VENCIDA",
        "ativo": true,
        "parametros": {}
      },
      {
        "codigo": "PRAZO_MAXIMO",
        "ativo": true,
        "parametros": {
          "prazo_maximo_dias": 180
        }
      },
      {
        "codigo": "CONCENTRACAO_MAXIMA_SACADO",
        "ativo": true,
        "parametros": {
          "percentual_maximo": 10.0,
          "agrupamento": "RAIZ_CNPJ"
        }
      },
      {
        "codigo": "PRAZO_MINIMO",
        "ativo": false,
        "parametros": {
          "prazo_minimo_dias": 30
        }
      },
      {
        "codigo": "CONCENTRACAO_MAXIMA_CEDENTE",
        "ativo": false,
        "parametros": {
          "percentual_maximo": 8.0
        }
      }
    ],
    "precificacao": {
      "metodo": "DESCONTO_SIMPLES",
      "taxa_mensal_percentual": 2.0,
      "base_dias": 30
    }
  }
  )
  const formData = new FormData()
  formData.append('file', selectedFile)
  formData.append('config', config.value)

  try {
    const response = await axios.post(
      'http://192.168.189.20:8000/api/validate',
      formData
    )

    result.value = response.data
    emit('upload-success', response.data)

  } catch (err) {
    error.value =
      err.response?.data?.detail ||
      'Erro ao enviar o arquivo.'

    emit('upload-error', err)

  } finally {
    loading.value = false
    event.target.value = ''
  }
}
</script>

<template>
  <div class="upload-form">
    <label class="upload-label" for="receivables-file">Arquivo de lastro</label>

    <label
      class="upload-dropzone"
      :class="{ 'upload-dropzone--disabled': loading }"
      for="receivables-file"
    >
      <span class="upload-icon" aria-hidden="true">
        <svg viewBox="0 0 40 40" fill="none">
          <path d="M11 5.5h11l8 8V32a2.5 2.5 0 0 1-2.5 2.5h-16A2.5 2.5 0 0 1 9 32V8a2.5 2.5 0 0 1 2-2.5Z" stroke="currentColor" stroke-width="1.6" />
          <path d="M22 6v8h8M14 22h11m-11 5h8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
          <path d="M20 17v7m-3-3 3-3 3 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </span>

      <span class="upload-copy">
        <strong>{{ file ? file.name : 'Selecione seu arquivo CSV' }}</strong>
        <span>{{ loading ? 'Enviando arquivo...' : 'Escolha um arquivo do seu dispositivo' }}</span>
      </span>

      <span v-if="loading" class="upload-spinner" aria-label="Enviando"></span>
      <span v-else class="upload-action">Escolher arquivo</span>

      <input
        id="receivables-file"
        type="file"
        accept=".csv,text/csv"
        :disabled="loading"
        @change="handleFile"
      />
    </label>

    <p class="upload-format">Tamanho máximo recomendado: 20 MB</p>

    <p v-if="error" class="upload-message upload-message--error" role="alert">
      {{ error }}
    </p>

    <p v-if="result" class="upload-message upload-message--success" role="status">
      Arquivo enviado com sucesso. Confira o resultado da análise abaixo.
    </p>
  </div>
</template>
