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
const config = ref(JSON.parse(JSON.stringify(defaultConfig)))
const configDialog = ref(null)
const configDraft = ref(JSON.parse(JSON.stringify(defaultConfig)))
const configError = ref('')
const activeValidatorCount = computed(() =>
  Array.isArray(configDraft.value?.validadores)
    ? configDraft.value.validadores.filter(validator => validator.ativo).length
    : 0
)

function openConfigModal() {
  configDraft.value = JSON.parse(JSON.stringify(config.value))
  configError.value = ''
  configDialog.value?.showModal()
}

function saveConfiguration() {
  if (
    !Array.isArray(configDraft.value?.validadores) ||
    configDraft.value.validadores.some(
      validator => !validator || typeof validator.ativo !== 'boolean'
    )
  ) {
    configError.value = 'Não foi possível validar os critérios. Feche e abra novamente.'
    return
  }

  const invalidPricingValue = Object.entries(defaultConfig.precificacao).some(
    ([key, defaultValue]) =>
      typeof defaultValue === 'number' &&
      (typeof configDraft.value.precificacao?.[key] !== 'number' ||
        !Number.isFinite(configDraft.value.precificacao[key]) ||
        configDraft.value.precificacao[key] < 0 ||
        (isPercentageParameter(key) &&
          configDraft.value.precificacao[key] > 100))
  )
  const invalidValidatorValue = configDraft.value.validadores.some(validator => {
    const defaultValidator = defaultConfig.validadores.find(
      item => item.codigo === validator.codigo
    )

    return Object.entries(defaultValidator?.parametros ?? {}).some(
      ([key, defaultValue]) =>
        typeof defaultValue === 'number' &&
        (typeof validator.parametros?.[key] !== 'number' ||
          !Number.isFinite(validator.parametros[key]) ||
          validator.parametros[key] < 0 ||
          (isPercentageParameter(key) && validator.parametros[key] > 100))
    )
  })

  if (invalidPricingValue || invalidValidatorValue) {
    configError.value =
      'Preencha os campos numéricos com valores válidos. Percentuais devem ficar entre 0 e 100.'
    return
  }

  config.value = JSON.parse(JSON.stringify(configDraft.value))
  configDialog.value?.close()
}

function formatParameters(parameters) {
  return Object.entries(parameters ?? {})
    .filter(([, value]) => typeof value !== 'number')
    .map(([key, value]) => {
      const formattedValue = Array.isArray(value) ? value.join(', ') : value
      return `${key.replaceAll('_', ' ')}: ${formattedValue}`
    })
    .join(' · ')
}

function formatParameterLabel(key) {
  return key.replaceAll('_', ' ')
}

function isPercentageParameter(key) {
  return key.includes('percentual')
}

function parameterStep(key) {
  return key.endsWith('_dias') || key === 'base_dias' ? 1 : 'any'
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
          Ative ou desative os critérios que serão usados na validação.
        </p>

        <div class="config-summary">
          <span class="config-status-dot"></span>
          {{ activeValidatorCount }} de {{ configDraft?.validadores?.length ?? 0 }} validadores ativos
        </div>

        <div class="config-fund-summary">
          <div>
            <span>Fundo</span>
            <strong>{{ configDraft?.fundo?.nome }}</strong>
          </div>
          <div>
            <span>Precificação · {{ configDraft?.precificacao?.metodo?.replaceAll('_', ' ') }}</span>
            <label class="pricing-number-field">
              <span class="mx-2">Taxa mensal (%)</span>
              <input
                v-model.number="configDraft.precificacao.taxa_mensal_percentual"
                type="number"
                min="0"
                max="100"
                step="any"
                aria-label="Taxa mensal da precificação em percentual"
              />
            </label>
            <label class="pricing-number-field ">
              <span class="mx-2">Base de dias</span>
              <input
                v-model.number="configDraft.precificacao.base_dias"
                type="number"
                min="0"
                step="1"
                aria-label="Base de dias da precificação"
              />
            </label>
          </div>
        </div>

        <fieldset class="validator-list">
          <legend class="config-editor-label">Critérios de validação</legend>
          <div
            v-for="(validator, index) in configDraft?.validadores ?? []"
            :key="validator.codigo"
            class="validator-row"
            :class="{ 'validator-row--inactive': !validator.ativo }"
          >
            <div class="validator-copy">
              <strong>{{ validator.codigo.replaceAll('_', ' ') }}</strong>
              <span v-if="formatParameters(validator.parametros)">
                {{ formatParameters(validator.parametros) }}
              </span>
              <div
                v-if="Object.values(validator.parametros ?? {}).some(value => typeof value === 'number')"
                class="validator-number-fields"
              >
                <template
                  v-for="(value, key) in validator.parametros"
                  :key="key"
                >
                  <label
                    v-if="typeof value === 'number'"
                    class="validator-number-field"
                  >
                    <span>{{ formatParameterLabel(key) }}</span>
                    <input
                      v-model.number="validator.parametros[key]"
                      type="number"
                      min="0"
                      :max="isPercentageParameter(key) ? 100 : undefined"
                      :step="parameterStep(key)"
                      :aria-label="`${formatParameterLabel(key)} para ${validator.codigo.replaceAll('_', ' ')}`"
                    />
                  </label>
                </template>
              </div>
            </div>
            <input
              v-model="validator.ativo"
              type="checkbox"
              :aria-label="`Ativar ${validator.codigo.replaceAll('_', ' ')}`"
              :aria-describedby="`validator-state-${index}`"
            />
            <span
              :id="`validator-state-${index}`"
              class="validator-state"
            >
              {{ validator.ativo ? 'Ativo' : 'Inativo' }}
            </span>
          </div>
        </fieldset>

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
          <button class="config-save" type="submit">Salvar critérios</button>
        </div>
      </form>
    </dialog>
  </div>
</template>
