<script setup>
import FileUpload from './components/FileUpload.vue'
</script>

<template>

  <FileUpload
      @upload-success="handleSuccess"
      @upload-error="handleError"
    />
   <ValidationResults
      v-if="hasResults"
      :results="results"
    />
</template>
