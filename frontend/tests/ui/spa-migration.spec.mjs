import { test, expect } from '@playwright/test'
import { mockApp } from './fixtures.mjs'

test('a redirected search bookmark opens the palette with its original source and query', async ({
  page,
}) => {
  await mockApp(page)
  await page.goto('/app/?q=naruto&source=voir-anime&search=1&lang=en')
  await expect(page.locator('.palette-card')).toBeVisible()
  await expect(page.locator('.palette-search-input')).toHaveValue('naruto')
  await expect(page.locator('.palette-card select')).toHaveValue('voir-anime')
})

test('a search bookmark without a query still opens the search dialog', async ({ page }) => {
  await mockApp(page)
  await page.goto('/app/?search=1')
  await expect(page.locator('.palette-card')).toBeVisible()
  await expect(page.locator('.palette-search-input')).toHaveValue('')
})
