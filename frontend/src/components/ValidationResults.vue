
<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  results: {
    type: Array,
    default: () => []
  }
})

const filter = ref('TODOS')
const search = ref('')
const currentPage = ref(1)
const pageSize = 10

const approved = computed(() =>
  props.results.filter(r => r.status === 'APROVADO').length
)

const rejected = computed(() =>
  props.results.filter(r => r.status === 'BARRADO').length
)

const approvalRate = computed(() =>
  props.results.length
    ? ((approved.value / props.results.length) * 100).toFixed(1)
    : '0.0'
)

const filteredResults = computed(() => {
  return props.results.filter(r => {
    const matchStatus =
      filter.value === 'TODOS' || r.status === filter.value

    const matchSearch =
      String(r.id ?? '').toLowerCase()
        .includes(search.value.toLowerCase()) ||
      String(r.linha).includes(search.value)

    return matchStatus && matchSearch
  })
})

const totalPages = computed(() =>
  Math.max(1, Math.ceil(filteredResults.value.length / pageSize))
)

const paginatedResults = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredResults.value.slice(start, start + pageSize)
})

function setFilter(value) {
  filter.value = value
  currentPage.value = 1
}

function formatReason(reason) {
  return reason.replaceAll('_', ' ')
}
</script>

<template>
  <div class="w-full space-y-6">

    <!-- Summary -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">

      <div class="rounded-xl border border-gray-200 bg-white p-5">
        <p class="text-sm text-gray-500">Total de registros</p>
        <p class="mt-2 text-3xl font-bold text-gray-900">
          {{ results.length }}
        </p>
      </div>

      <div class="rounded-xl border border-green-200 bg-green-50 p-5">
        <p class="text-sm text-green-700">Aprovados</p>
        <p class="mt-2 text-3xl font-bold text-green-700">
          {{ approved }}
        </p>
      </div>

      <div class="rounded-xl border border-red-200 bg-red-50 p-5">
        <p class="text-sm text-red-700">Barrados</p>
        <p class="mt-2 text-3xl font-bold text-red-700">
          {{ rejected }}
        </p>
      </div>
    </div>

    <!-- Approval rate -->
    <div class="rounded-xl border border-gray-200 bg-white p-5">
      <div class="mb-3 flex justify-between text-sm">
        <span class="font-medium text-gray-700">
          Taxa de aprovação
        </span>
        <span class="font-semibold text-gray-900">
          {{ approvalRate }}%
        </span>
      </div>

      <div class="h-3 overflow-hidden rounded-full bg-red-100">
        <div
          class="h-full rounded-full bg-green-500 transition-all"
          :style="{ width: approvalRate + '%' }"
        ></div>
      </div>
    </div>

    <!-- Results table -->
    <div class="overflow-hidden rounded-xl border border-gray-200 bg-white">

      <div class="flex flex-wrap items-center justify-between gap-4 border-b p-5">
        <h2 class="text-lg font-semibold text-gray-900">
          Resultado da validação
        </h2>

        <input
          v-model="search"
          @input="currentPage = 1"
          type="text"
          placeholder="Buscar por ID ou linha..."
          class="rounded-lg border border-gray-300 px-3 py-2 text-sm
                 outline-none focus:border-blue-500"
        />
      </div>

      <!-- Filters -->
      <div class="flex gap-2 border-b p-4">
        <button
          v-for="item in ['TODOS', 'APROVADO', 'BARRADO']"
          :key="item"
          @click="setFilter(item)"
          class="rounded-lg px-4 py-2 text-sm font-medium transition"
          :class="filter === item
            ? 'bg-blue-600 text-white'
            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'"
        >
          {{ item === 'TODOS' ? 'Todos' :
             item === 'APROVADO' ? 'Aprovados' : 'Barrados' }}
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th class="px-5 py-4">Linha</th>
              <th class="px-5 py-4">ID do documento</th>
              <th class="px-5 py-4">Status</th>
              <th class="px-5 py-4">Motivo</th>
            </tr>
          </thead>

          <tbody class="divide-y divide-gray-100">
            <tr
              v-for="record in paginatedResults"
              :key="record.linha"
              class="hover:bg-gray-50"
            >
              <td class="px-5 py-4 text-gray-500">
                #{{ record.linha }}
              </td>

              <td class="px-5 py-4 font-medium text-gray-900">
                {{ record.id }}
              </td>

              <td class="px-5 py-4">
                <span
                  class="inline-flex rounded-full px-3 py-1 text-xs font-semibold"
                  :class="record.status === 'APROVADO'
                    ? 'bg-green-100 text-green-700'
                    : 'bg-red-100 text-red-700'"
                >
                  {{ record.status === 'APROVADO' ? '✓ ' : '✕ ' }}
                  {{ record.status }}
                </span>
              </td>

              <td class="px-5 py-4">
                <div
                  v-if="record.barrado_por?.length"
                  class="flex flex-wrap gap-2"
                >
                  <span
                    v-for="reason in record.barrado_por"
                    :key="reason"
                    :title="reason"
                    class="rounded-md bg-red-50 px-2 py-1
                           text-xs text-red-700"
                  >
                    {{ formatReason(reason) }}
                  </span>
                </div>

                <span v-else class="text-gray-400">—</span>
              </td>
            </tr>

            <tr v-if="!paginatedResults.length">
              <td colspan="4" class="px-5 py-10 text-center text-gray-500">
                Nenhum registro encontrado.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex items-center justify-between border-t p-4">
        <span class="text-sm text-gray-500">
          {{ filteredResults.length }} registros encontrados
        </span>

        <div class="flex items-center gap-3">
          <button
            @click="currentPage--"
            :disabled="currentPage === 1"
            class="rounded-lg border px-3 py-2 text-sm
                   disabled:cursor-not-allowed disabled:opacity-40"
          >
            Anterior
          </button>

          <span class="text-sm text-gray-600">
            {{ currentPage }} / {{ totalPages }}
          </span>

          <button
            @click="currentPage++"
            :disabled="currentPage >= totalPages"
            class="rounded-lg border px-3 py-2 text-sm
                   disabled:cursor-not-allowed disabled:opacity-40"
          >
            Próxima
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
