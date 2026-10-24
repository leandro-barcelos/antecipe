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
    console.log(formData.get('config'))
    console.log('Enviando arquivo:', selectedFile.name)
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
  <div class="w-full space-y-3">

    <label class="block text-sm font-semibold text-gray-700">
      Arquivo de Lato
    </label>

    <label class="flex w-full cursor-pointer items-center gap-4
             rounded-xl border-2 border-dashed border-gray-300
             bg-white p-5 transition hover:border-blue-500
             hover:bg-blue-50" :class="{ 'pointer-events-none opacity-60': loading }">
      <span class="text-3xl">📄</span>

      <div class="flex-1">
        <p class="text-sm font-medium text-gray-800">
          {{ file ? file.name : 'Selecione um arquivo CSV' }}
        </p>

        <p class="mt-1 text-xs text-gray-500">
          {{ loading ? 'Enviando arquivo...' : 'Formato aceito: .csv' }}
        </p>
      </div>

      <span v-if="loading" class="h-5 w-5 animate-spin rounded-full
               border-2 border-blue-500 border-t-transparent"></span>

      <span v-else class="text-xl text-gray-400">↑</span>

      <input type="file" accept=".csv,text/csv" class="hidden" :disabled="loading" @change="handleFile" />
    </label>

    <p v-if="error" class="text-sm text-red-600">
      {{ error }}
    </p>

    <p v-if="result" class="text-sm text-green-600">
      Arquivo enviado com sucesso!
    </p>

  </div>
</template>
