package ooo

object CollectionReadProfileJson {
    private def quote(value: String): String = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    def json(value: Any): String = value match {
        case null => "null"
        case text: String => quote(text)
        case bool: Boolean => bool.toString
        case number: BigInt => number.toString
        case number: Int => number.toString
        case number: Long => number.toString
        case option: Option[_] => option.map(json).getOrElse("null")
        case fields: collection.Map[_, _] => fields.toSeq.sortBy(_._1.toString)
            .map { case (name, item) => quote(name.toString) + ":" + json(item) }.mkString("{", ",", "}")
        case items: Seq[_] => items.map(json).mkString("[", ",", "]")
        case product: Product => json(product.productElementNames.zip(product.productIterator).toMap)
        case other => throw new IllegalArgumentException("unserialized profile value: " + other.getClass.getName)
    }
}
