import { describe, expect, it } from 'vitest'
import fs from 'fs'
import path from 'path'

// Регресія: локальна змінна з імʼям `t` затіняє функцію перекладу t() і ламає рендер
// (так зник стіл після «Спіймати» в режимі «Шулер»).
const files = []
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).forEach((e) => {
  const p = path.join(d, e.name)
  if (e.isDirectory()) walk(p)
  else if (/\.jsx?$/.test(e.name) && !/test|i18n|sounds/.test(e.name)) files.push(p)
})
walk(path.join(__dirname))

describe('i18n', () => {
  it('ніде не затіняється функція t()', () => {
    for (const f of files) {
      const src = fs.readFileSync(f, 'utf8')
      if (!/import \{[^}]*\bt\b[^}]*\} from '.*i18n/.test(src)) continue
      expect(src, f).not.toMatch(/\b(const|let|var)\s+t\s*=/)
      expect(src, f).not.toMatch(/\(\s*t\s*(,[^)]*)?\)\s*=>/)
    }
  })
})
