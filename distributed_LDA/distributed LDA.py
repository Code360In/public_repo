# Databricks notebook source
# MAGIC %md
# MAGIC # Spark NLPとSpark MLLib(LDA)を用いた分散トピックモデリング
# MAGIC 
# MAGIC - [Distributed Topic Modelling using Spark NLP and Spark MLLib\(LDA\) \| by Satish Silveri \| Analytics Vidhya \| Medium](https://medium.com/analytics-vidhya/distributed-topic-modelling-using-spark-nlp-and-spark-mllib-lda-6db3f06a4da3)
# MAGIC - [Spark NLPとSpark MLLib\(LDA\)を用いた分散トピックモデリング \- Qiita](https://qiita.com/taka_yayoi/items/d639ec54a3fd751aad0a)

# COMMAND ----------

# MAGIC %md
# MAGIC ## ライブラリのインストール&インポート
# MAGIC 
# MAGIC 以下のライブラリに加えて、クラスターライブラリとしてMaven経由で`com.johnsnowlabs.nlp:spark-nlp-spark32_2.12:3.4.4`をインストールします。
# MAGIC 
# MAGIC https://github.com/JohnSnowLabs/spark-nlp#apache-spark-32x-scala-212

# COMMAND ----------

# Install PySpark and Spark NLP
%pip install -q pyspark==3.1.2 spark-nlp

# Install Spark NLP Display lib
%pip install --upgrade -q spark-nlp-display

# COMMAND ----------

# Spark NLPのインポート
from sparknlp.base import *
from sparknlp.annotator import *
from sparknlp.pretrained import PretrainedPipeline
import sparknlp
from pyspark.sql import SparkSession
from pyspark.ml import Pipeline

# COMMAND ----------

# MAGIC %md
# MAGIC ## データのロード
# MAGIC 
# MAGIC 1. [こちら](https://github.com/ravishchawla/topic_modeling/blob/master/data/abcnews-date-text.csv)からCSVファイルをダウンロードします。
# MAGIC 1. サイドメニューの**データ**をクリックし、**アップロード**ボタンをクリックします。
# MAGIC 1. アップロードするパスを選択して、CSVファイルをドラッグ&ドロップします。
# MAGIC 
# MAGIC 　以下の例では、下のパスにアップロードしています。
# MAGIC > `dbfs:/FileStore/shared_uploads/takaaki.yayoi@databricks.com/news/abcnews_date_text.csv`

# COMMAND ----------

file_location = "dbfs:/FileStore/shared_uploads/takaaki.yayoi@databricks.com/news/abcnews_date_text.csv"
file_type = "csv"

# CSVのオプション
infer_schema = "true"
first_row_is_header = "true"
delimiter = ","

df = spark.read.format(file_type) \
  .option("inferSchema", infer_schema) \
  .option("header", first_row_is_header) \
  .option("sep", delimiter) \
  .load(file_location)

# レコード数の確認
df.count()

# COMMAND ----------

display(df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Spark NLPを用いた前処理パイプライン

# COMMAND ----------

# Spark NLPはドキュメントに変換する入力データフレームあるいはカラムが必要です
document_assembler = DocumentAssembler() \
    .setInputCol("headline_text") \
    .setOutputCol("document") \
    .setCleanupMode("shrink")

# 文をトークンに分割(array)
tokenizer = Tokenizer() \
  .setInputCols(["document"]) \
  .setOutputCol("token")

# 不要な文字やゴミを除外
normalizer = Normalizer() \
    .setInputCols(["token"]) \
    .setOutputCol("normalized")

# ストップワードの除外
stopwords_cleaner = StopWordsCleaner()\
      .setInputCols("normalized")\
      .setOutputCol("cleanTokens")\
      .setCaseSensitive(False)

# 原型にするための単語のステミング
stemmer = Stemmer() \
    .setInputCols(["cleanTokens"]) \
    .setOutputCol("stem")

# Finisherは最も重要なアノテーターです。Spark NLPはデータフレームの各行をドキュメントに変換する際に自身の構造を追加します。Finisherは期待される構造、すなわち、トークンの配列に戻す助けをしてくれます。 
finisher = Finisher() \
    .setInputCols(["stem"]) \
    .setOutputCols(["tokens"]) \
    .setOutputAsArray(True) \
    .setCleanAnnotations(False)

# それぞれのフェーズが順番に実行されるようにパイプラインを構築します。このパイプラインはモデルのテストにも使うことができます。
nlp_pipeline = Pipeline(
    stages=[document_assembler, 
            tokenizer,
            normalizer,
            stopwords_cleaner, 
            stemmer, 
            finisher])

# パイプラインのトレーニング
nlp_model = nlp_pipeline.fit(df)

# データフレームを変換するためにパイプラインを適用します。
processed_df  = nlp_model.transform(df)

# NLPパイプラインは我々にとって不要な中間カラムを作成します。なので、必要なカラムのみを選択します。
tokens_df = processed_df.select('publish_date','tokens').limit(10000)

display(tokens_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 特徴量エンジニアリング

# COMMAND ----------

from pyspark.ml.feature import CountVectorizer

cv = CountVectorizer(inputCol="tokens", outputCol="features", vocabSize=500, minDF=3.0)

# モデルのトレーニング
cv_model = cv.fit(tokens_df)

# データを変換します。出力カラムが特徴量となります。
vectorized_tokens = cv_model.transform(tokens_df)

# COMMAND ----------

display(vectorized_tokens)

# COMMAND ----------

# MAGIC %md
# MAGIC ## LDAモデルの構築

# COMMAND ----------

from pyspark.ml.clustering import LDA

num_topics = 3

lda = LDA(k=num_topics, maxIter=10)
model = lda.fit(vectorized_tokens)

ll = model.logLikelihood(vectorized_tokens)
lp = model.logPerplexity(vectorized_tokens)

print("The lower bound on the log likelihood of the entire corpus: " + str(ll))
print("The upper bound on perplexity: " + str(lp))

# COMMAND ----------

# MAGIC %md
# MAGIC ## トピックの可視化

# COMMAND ----------

# CountVectorizerからボキャブラリーを抽出
vocab = cv_model.vocabulary

topics = model.describeTopics()   
topics_rdd = topics.rdd

topics_words = topics_rdd\
       .map(lambda row: row['termIndices'])\
       .map(lambda idx_list: [vocab[idx] for idx in idx_list])\
       .collect()

for idx, topic in enumerate(topics_words):
    print("topic: {}".format(idx))
    print("*"*25)
    for word in topic:
       print(word)
    print("*"*25)

# COMMAND ----------

# MAGIC %md
# MAGIC # END
