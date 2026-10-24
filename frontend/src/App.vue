<script setup>
import { computed, ref } from 'vue'
import FileUpload from './components/FileUpload.vue'
import ValidationResults from './components/ValidationResults.vue'

const results = ref([])
const responseError = ref('')
const hasResults = computed(() => results.value.length > 0)

function handleSuccess(response) {
  const rows = Array.isArray(response)
    ? response
    : response?.resultados ?? response?.results

  if (!Array.isArray(rows)) {
    responseError.value =
      'A validação foi concluída, mas a API retornou um formato de resultado inesperado.'
    results.value = []
    return
  }

  responseError.value = ''
  results.value = rows
}

function handleError() {
  results.value = []
  responseError.value = ''
}
</script>

<template>
  <div class="app-shell">
    <header class="site-header">
      <a class="brand" href="#" aria-label="Antecipe - início">
        <svg class="brand-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true">
          <path d="M5 8.5 12.5 4 27 12.5 19.5 17 5 8.5Z" fill="currentColor" />
          <path d="M5 13.5 12.5 9 27 17.5 19.5 22 5 13.5Z" fill="currentColor" opacity=".72" />
          <path d="M5 18.5 12.5 14 27 22.5 19.5 27 5 18.5Z" fill="currentColor" opacity=".46" />
        </svg>
        <span>antecipe</span>
      </a>

      <span class="header-caption">INTELIGÊNCIA EM RECEBÍVEIS</span>
      <a class="header-link" href="#resultados">Resultados <span aria-hidden="true">↘</span></a>
    </header>

    <main class="page-content">
      <section class="intro-section" aria-labelledby="page-title">
        <p class="eyebrow"><span></span> ANÁLISE DE CARTEIRA</p>
        <h1 id="page-title">Decisões melhores<br />começam com <em>clareza.</em></h1>
        <p class="intro-copy">
          Envie sua carteira de recebíveis e confira a elegibilidade de cada operação
          com uma análise simples, segura e transparente.
        </p>
      </section>

      <section class="workflow-card" aria-labelledby="upload-title">
        <div class="workflow-heading">
          <div>
            <p class="section-kicker">01 / ENVIO DE ARQUIVO</p>
            <h2 id="upload-title">Comece por aqui</h2>
          </div>
          <span class="workflow-tag">CSV</span>
        </div>

        <FileUpload
          @upload-success="handleSuccess"
          @upload-error="handleError"
        />

        <div class="privacy-note">
          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="M10 2.5 16 5v4.4c0 3.8-2.6 6.6-6 8.1-3.4-1.5-6-4.3-6-8.1V5l6-2.5Z" stroke="currentColor" stroke-width="1.4" />
            <path d="m7.5 9.8 1.7 1.7 3.5-3.7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span>Seus dados são tratados com segurança durante toda a análise.</span>
        </div>
      </section>

      <p v-if="responseError" class="response-error" role="alert">
        {{ responseError }}
      </p>

      <section v-if="hasResults" id="resultados" class="results-section" aria-labelledby="results-title">
        <div class="results-heading">
          <div>
            <p class="section-kicker">02 / ANÁLISE CONCLUÍDA</p>
            <h2 id="results-title">Visão da carteira</h2>
          </div>
          <a class="back-to-top" href="#">Voltar ao início ↑</a>
        </div>
        <ValidationResults :results="results" />
      </section>
    </main>

    <footer class="site-footer">
      <a class="footer-brand" href="#">antecipe</a>
      <span>Crédito com mais clareza.</span>
    </footer>
  </div>
</template>
