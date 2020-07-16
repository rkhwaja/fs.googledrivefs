def MimeTypeEquals(argument):
	return lambda: f"mimeType = '{argument}'"

def NameEquals(argument):
	return lambda: f"name = '{argument}'"

def And(argument1, argument2):
	return lambda: f"({argument1()}) and ({argument2()})"
