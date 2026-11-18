import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir:'./e2e',
  workers:1,
  use:{baseURL:process.env.CAMPUSFLOW_E2E_URL??'http://127.0.0.1:8767',viewport:{width:360,height:800}},
})
