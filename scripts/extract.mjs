import WordExtractor from 'word-extractor'

const document = await new WordExtractor().extract(process.argv[2])
process.stdout.write(JSON.stringify([document.getBody()]))
