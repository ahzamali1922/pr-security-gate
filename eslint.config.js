module.exports = [
    {
        files: ["**/*.js"],

        languageOptions: {
            ecmaVersion: "latest",
            sourceType: "commonjs",

            globals: {
                console: "readonly",
                require: "readonly"
            }
        },

        rules: {
            "no-unused-vars": "error",
            "no-console": "warn"
        }
    }
];