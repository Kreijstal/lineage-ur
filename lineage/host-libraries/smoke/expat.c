#include <expat.h>
#include <stdio.h>
#include <string.h>

struct observations { int starts, ends, valid; char text[32]; size_t size; };
static void start(void *data, const XML_Char *name, const XML_Char **attributes) {
    struct observations *o = data;
    ++o->starts;
    if (o->starts == 1 && strcmp(name, "urn:lab|root")) o->valid = 0;
    if (o->starts == 2 && (strcmp(name, "urn:lab|item") || !attributes[0] || !attributes[1]
                         || strcmp(attributes[0], "id") || strcmp(attributes[1], "42"))) o->valid = 0;
}
static void end(void *data, const XML_Char *name) { (void)name; ++((struct observations *)data)->ends; }
static void text(void *data, const XML_Char *value, int length) {
    struct observations *o = data;
    if (o->size + length >= sizeof o->text) { o->valid = 0; return; }
    memcpy(o->text + o->size, value, length); o->size += length;
}
int main(void) {
    struct observations o = {.valid = 1};
    XML_Parser parser = XML_ParserCreateNS(NULL, '|');
    if (!parser) return 1;
    XML_SetUserData(parser, &o);
    XML_SetElementHandler(parser, start, end);
    XML_SetCharacterDataHandler(parser, text);
    const char *first = "<root xmlns='urn:lab'><item id='42'>hello &amp;";
    const char *second = " goodbye</item></root>";
    if (XML_Parse(parser, first, strlen(first), 0) != XML_STATUS_OK) return 2;
    if (XML_Parse(parser, second, strlen(second), 1) != XML_STATUS_OK) return 3;
    if (!o.valid || o.starts != 2 || o.ends != 2 || strcmp(o.text, "hello & goodbye")) return 4;
    XML_ParserFree(parser);
    parser = XML_ParserCreate(NULL);
    if (!parser) return 5;
    if (XML_Parse(parser, "<a></b>", 7, 1) != XML_STATUS_ERROR || XML_GetErrorCode(parser) != XML_ERROR_TAG_MISMATCH) return 6;
    XML_ParserFree(parser);
    puts("Expat incremental parsing, namespaces, entities and malformed XML: PASS");
    return 0;
}
