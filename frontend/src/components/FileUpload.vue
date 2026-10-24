<script setup>
import { computed, ref } from 'vue'
import axios from 'axios'

const emit = defineEmits(['upload-success', 'upload-error'])

const defaultConfig = {
  fundo: {
    nome: 'ANTECIPE FIDC',
    cnpj: '92.234.400/0001-80'
  },
  validadores: [
    {
      codigo: 'CNPJ_SACADO_VALIDO',
      ativo: true,
      parametros: {}
    },
    {
      codigo: 'SITUACAO_CADASTRAL_SACADO',
      ativo: true,
      parametros: {
        situacoes_aceitas: ['ATIVA']
      }
    },
    {
      codigo: 'TIPO_RECEBIVEL',
      ativo: true,
      parametros: {
        tipos_aceitos: ['Duplicata', 'Duplicata de Serviço']
      }
    },
    {
      codigo: 'VALOR_MINIMO',
      ativo: true,
      parametros: {
        valor_minimo: 100.0
      }
    },
    {
      codigo: 'NAO_VENCIDA',
      ativo: true,
      parametros: {}
    },
    {
      codigo: 'PRAZO_MAXIMO',
      ativo: true,
      parametros: {
        prazo_maximo_dias: 180
      }
    },
    {
      codigo: 'CONCENTRACAO_MAXIMA_SACADO',
      ativo: true,
      parametros: {
        percentual_maximo: 10.0,
        agrupamento: 'RAIZ_CNPJ'
      }
    },
    {
      codigo: 'PRAZO_MINIMO',
      ativo: false,
      parametros: {
        prazo_minimo_dias: 30
      }
    },
    {
      codigo: 'CONCENTRACAO_MAXIMA_CEDENTE',
      ativo: false,
      parametros: {
        percentual_maximo: 8.0
      }
    }
  ],
  precificacao: {
    metodo: 'DESCONTO_SIMPLES',
    taxa_mensal_percentual: 2.0,
    base_dias: 30
  }
}

const file = ref(null)
const loading = ref(false)
const error = ref('')
const result = ref(null)
const config = ref(defaultConfig)
const configDialog = ref(null)
const configDraft = ref('')
const configError = ref('')
const activeValidatorCount = computed(() =>
  Array.isArray(config.value.validadores)
    ? config.value.validadores.filter(validator => validator?.ativo).length
    : 0
)

function openConfigModal() {
  configDraft.value = JSON.stringify(config.value, null, 2)
  configError.value = ''
  configDialog.value?.showModal()
}

function saveConfiguration() {
  let parsedConfig

  try {
    parsedConfig = JSON.parse(configDraft.value)
  } catch {
    configError.value = 'JSON inválido. Corrija a sintaxe antes de salvar.'
    return
  }

  if (!parsedConfig || typeof parsedConfig !== 'object' || Array.isArray(parsedConfig)) {
    configError.value = 'A configuração deve ser um objeto JSON.'
    return
  }

  config.value = parsedConfig
  configDialog.value?.close()
}

function handleFile(event) {
  const selectedFile = event.target.files?.[0]
  if (!selectedFile) return

  if (!selectedFile.name.toLowerCase().endsWith('.csv')) {
    file.value = null
    result.value = null
    error.value = 'Selecione um arquivo CSV válido.'
    event.target.value = ''
    return
  }

  file.value = selectedFile
  error.value = ''
  result.value = null
  event.target.value = ''
}

async function uploadFile() {
  if (!file.value || loading.value) return

  const formData = new FormData()
  formData.append('file', file.value)
  formData.append('config', JSON.stringify(config.value))

  loading.value = true
  error.value = ''
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
  }
}
</script>

<template>
  <div class="upload-form">
    <div class="upload-controls">
      <label class="upload-label" for="receivables-file">Arquivo de lastro</label>
      <button
        class="config-edit-button"
        type="button"
        :disabled="loading"
        @click="openConfigModal"
      >
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M10 3v14M3 10h14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
        </svg>
        Ver / editar configuração
      </button>
    </div>

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
        <span>{{ loading ? 'Enviando arquivo...' : file ? 'Arquivo pronto para análise' : 'Escolha um arquivo do seu dispositivo' }}</span>
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

    <div class="upload-footer" style="margin: 20px;">
      <p class="upload-format">Tamanho máximo recomendado: 20 MB</p>
      <button
        v-if="file"
        class="upload-submit"
        type="button"
        :disabled="loading"
        @click="uploadFile"
      >
        <span v-if="loading" class="upload-spinner upload-spinner--light" aria-hidden="true"></span>
        {{ loading ? 'Enviando...' : 'Enviar arquivo' }}
        <span v-if="!loading" aria-hidden="true">→</span>
      </button>
    </div>

    <p v-if="error" class="upload-message upload-message--error" role="alert">
      {{ error }}
    </p>

    <p v-if="result" class="upload-message upload-message--success" role="status">
      Arquivo enviado com sucesso. Confira o resultado da análise abaixo.
    </p>

    <dialog
      ref="configDialog"
      class="config-dialog"
      aria-labelledby="config-title"
    >
      <form class="config-dialog-content" @submit.prevent="saveConfiguration">
        <div class="config-dialog-heading">
          <div>
            <p class="section-kicker">CONFIGURAÇÃO DA ANÁLISE</p>
            <h2 id="config-title">Critérios de validação</h2>
          </div>
          <button
            class="config-close"
            type="button"
            aria-label="Fechar"
            @click="configDialog?.close()"
          >
            ×
          </button>
        </div>

        <p class="config-description">
          Revise ou edite o JSON. As alterações serão usadas no próximo envio.
        </p>

        <div class="config-summary">
          <span class="config-status-dot"></span>
          Na configuração salva: {{ activeValidatorCount }} validadores ativos
        </div>

        <label class="config-editor-label" for="config-json">Configuração em JSON</label>
        <textarea
          id="config-json"
          v-model="configDraft"
          class="config-editor"
          spellcheck="false"
          autocapitalize="off"
          autocomplete="off"
          autocorrect="off"
          :aria-describedby="configError ? 'config-help config-error' : 'config-help'"
        ></textarea>
        <p id="config-help" class="config-help">
          Informe um objeto JSON válido para atualizar a configuração.
        </p>
        <p
          v-if="configError"
          id="config-error"
          class="upload-message upload-message--error"
          role="alert"
        >
          {{ configError }}
        </p>

        <div class="config-dialog-actions">
          <button
            class="config-cancel"
            type="button"
            @click="configDialog?.close()"
          >
            Cancelar
          </button>
          <button class="config-save" type="submit">Salvar configuração</button>
        </div>
      </form>
    </dialog>
  </div>
</template>
