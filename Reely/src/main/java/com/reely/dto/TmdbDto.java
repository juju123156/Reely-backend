package com.reely.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class TmdbDto {

    private boolean adult;

    @JsonProperty("also_known_as")
    private List<String> alsoKnownAs;

    private String biography;
    private String birthday;
    private String deathday;
    private int gender;
    private String homepage;
    private int id;

    @JsonProperty("imdb_id")
    private String imdbId;

    @JsonProperty("known_for_department")
    private String knownForDepartment;

    private String name;

    @JsonProperty("place_of_birth")
    private String placeOfBirth;

    private double popularity;

    @JsonProperty("profile_path")
    private String profilePath;

    @JsonProperty("backdrop_path")
    private String backdropPath;

    @JsonProperty("belongs_to_collection")
    private Object belongsToCollection;

    private int budget;
    private List<Genre> genres;

    @JsonProperty("origin_country")
    private List<String> originCountry;

    @JsonProperty("original_language")
    private String originalLanguage;

    @JsonProperty("original_title")
    private String originalTitle;

    private String overview;

    @JsonProperty("poster_path")
    private String posterPath;

    @JsonProperty("production_companies")
    private List<ProductionCompany> productionCompanies;

    @JsonProperty("production_countries")
    private List<ProductionCountry> productionCountries;

    @JsonProperty("release_date")
    private String releaseDate;

    private long revenue;
    private int runtime;

    @JsonProperty("spoken_languages")
    private List<SpokenLanguage> spokenLanguages;

    private String status;
    private String tagline;
    private String title;
    private boolean video;

    @JsonProperty("vote_average")
    private double voteAverage;

    @JsonProperty("vote_count")
    private int voteCount;

    private Images images;

    // 확장 필드 (불필요할 경우 삭제 가능)
    @JsonProperty("iso_3166_1")
    private String iso_3166_1;

    @Data
    public static class Genre {
        private int id;
        private String name;
    }

    @Data
    public static class ProductionCompany {
        private int id;

        @JsonProperty("logo_path")
        private String logoPath;

        private String name;

        @JsonProperty("origin_country")
        private String originCountry;
    }

    @Data
    public static class ProductionCountry {
        @JsonProperty("iso_3166_1")
        private String iso_3166_1;

        private String name;
    }

    @Data
    public static class SpokenLanguage {
        @JsonProperty("english_name")
        private String englishName;

        @JsonProperty("iso_639_1")
        private String iso_3166_1;

        private String name;
    }

    @Data
    public static class Images {
        private List<Object> backdrops;
        private List<Object> logos;
        private List<Object> posters;
    }

    @Data
    public class PersonResult {
        private boolean adult;
        private int gender;
        private int id;

        @JsonProperty("known_for_department")
        private String knownForDepartment;

        private String name;

        @JsonProperty("original_name")
        private String originalName;

        private double popularity;

        @JsonProperty("profile_path")
        private String profilePath;

        @JsonProperty("known_for")
        private List<KnownFor> knownFor;
    }

    @Data
    public class KnownFor {
        @JsonProperty("backdrop_path")
        private String backdropPath;

        private int id;
        private String title;

        @JsonProperty("original_title")
        private String originalTitle;

        private String overview;

        @JsonProperty("poster_path")
        private String posterPath;

        @JsonProperty("media_type")
        private String mediaType;

        private boolean adult;

        @JsonProperty("original_language")
        private String originalLanguage;

        @JsonProperty("genre_ids")
        private List<Integer> genreIds;

        private double popularity;

        @JsonProperty("release_date")
        private String releaseDate;

        private boolean video;

        @JsonProperty("vote_average")
        private double voteAverage;

        @JsonProperty("vote_count")
        private int voteCount;
    }
}
