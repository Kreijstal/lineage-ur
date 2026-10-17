/* Exercise both packaged libraries with verified TLS 1.3 and application data. */
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/sha.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef OPENSSL_IS_BORINGSSL
#error This consumer must use the packaged BoringSSL headers.
#endif

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "failed at line %d: %s\n", __LINE__, #x); ERR_print_errors_fp(stderr); exit(1); } } while (0)

static void advance(SSL *ssl) {
    if (SSL_is_init_finished(ssl)) return;
    int result = SSL_do_handshake(ssl);
    if (result == 1) return;
    int error = SSL_get_error(ssl, result);
    CHECK(error == SSL_ERROR_WANT_READ || error == SSL_ERROR_WANT_WRITE);
}

int main(void) {
    static const unsigned char expected[SHA256_DIGEST_LENGTH] = {
        0xba,0x78,0x16,0xbf,0x8f,0x01,0xcf,0xea,0x41,0x41,0x40,0xde,0x5d,0xae,0x22,0x23,
        0xb0,0x03,0x61,0xa3,0x96,0x17,0x7a,0x9c,0xb4,0x10,0xff,0x61,0xf2,0x00,0x15,0xad
    };
    unsigned char digest[SHA256_DIGEST_LENGTH];
    CHECK(SHA256((const unsigned char *)"abc", 3, digest) != NULL);
    CHECK(memcmp(digest, expected, sizeof digest) == 0);

    EVP_PKEY_CTX *keygen = EVP_PKEY_CTX_new_id(EVP_PKEY_EC, NULL);
    EVP_PKEY *key = NULL;
    CHECK(keygen != NULL && EVP_PKEY_keygen_init(keygen) == 1);
    CHECK(EVP_PKEY_CTX_set_ec_paramgen_curve_nid(keygen, NID_X9_62_prime256v1) == 1);
    CHECK(EVP_PKEY_keygen(keygen, &key) == 1);
    X509 *cert = X509_new();
    CHECK(cert != NULL && X509_set_version(cert, 2) == 1);
    CHECK(ASN1_INTEGER_set(X509_get_serialNumber(cert), 1) == 1);
    CHECK(X509_gmtime_adj(X509_get_notBefore(cert), -60) != NULL);
    CHECK(X509_gmtime_adj(X509_get_notAfter(cert), 3600) != NULL);
    CHECK(X509_set_pubkey(cert, key) == 1);
    X509_NAME *name = X509_get_subject_name(cert);
    CHECK(X509_NAME_add_entry_by_txt(name, "CN", MBSTRING_ASC,
                                   (const unsigned char *)"lineage-ur.local", -1, -1, 0) == 1);
    CHECK(X509_set_issuer_name(cert, name) == 1);
    CHECK(X509_sign(cert, key, EVP_sha256()) > 0);

    SSL_CTX *server_ctx = SSL_CTX_new(TLS_method());
    SSL_CTX *client_ctx = SSL_CTX_new(TLS_method());
    CHECK(server_ctx != NULL && client_ctx != NULL);
    CHECK(SSL_CTX_set_min_proto_version(client_ctx, TLS1_3_VERSION) == 1);
    CHECK(SSL_CTX_set_max_proto_version(client_ctx, TLS1_3_VERSION) == 1);
    CHECK(SSL_CTX_use_certificate(server_ctx, cert) == 1);
    CHECK(SSL_CTX_use_PrivateKey(server_ctx, key) == 1);
    CHECK(X509_STORE_add_cert(SSL_CTX_get_cert_store(client_ctx), cert) == 1);
    SSL_CTX_set_verify(client_ctx, SSL_VERIFY_PEER, NULL);
    SSL *client = SSL_new(client_ctx), *server = SSL_new(server_ctx);
    CHECK(client != NULL && server != NULL);
    CHECK(X509_VERIFY_PARAM_set1_host(SSL_get0_param(client), "lineage-ur.local", strlen("lineage-ur.local")) == 1);
    BIO *client_bio = NULL, *server_bio = NULL;
    CHECK(BIO_new_bio_pair(&client_bio, 0, &server_bio, 0) == 1);
    SSL_set_bio(client, client_bio, client_bio);
    SSL_set_bio(server, server_bio, server_bio);
    SSL_set_connect_state(client);
    SSL_set_accept_state(server);
    for (int i = 0; i < 1000 && (!SSL_is_init_finished(client) || !SSL_is_init_finished(server)); ++i) {
        advance(client);
        advance(server);
    }
    CHECK(SSL_is_init_finished(client) && SSL_is_init_finished(server));
    CHECK(SSL_version(client) == TLS1_3_VERSION);
    CHECK(SSL_get_verify_result(client) == X509_V_OK);
    const char message[] = "lineage-ur packaged BoringSSL";
    char received[sizeof message];
    CHECK(SSL_write(client, message, sizeof message) == sizeof message);
    CHECK(SSL_read(server, received, sizeof received) == sizeof message);
    CHECK(memcmp(received, message, sizeof message) == 0);
    CHECK(SSL_write(server, received, sizeof received) == sizeof received);
    CHECK(SSL_read(client, received, sizeof received) == sizeof message);
    CHECK(memcmp(received, message, sizeof message) == 0);
    puts("BoringSSL SHA-256 vector, verified TLS 1.3 handshake and bidirectional data: PASS");
    SSL_free(client); SSL_free(server);
    SSL_CTX_free(client_ctx); SSL_CTX_free(server_ctx);
    X509_free(cert); EVP_PKEY_free(key); EVP_PKEY_CTX_free(keygen);
    return 0;
}
