package com.reely.common.util;

import java.io.*;
import java.net.*;
import java.nio.file.*;


public class CommonUtil {

    public static void fileDownloader(String fileUrl, String saveDir, String fileName) {
        try (InputStream in = new URL(fileUrl).openStream()) {
            String extension = "";
            // 디렉토리 없으면 생성
            Files.createDirectories(Paths.get(saveDir));
            // 🔍 URL에서 파일 확장자 추출
            int lastDotIndex = fileUrl.lastIndexOf(".");
            if (lastDotIndex != -1 && lastDotIndex < fileUrl.length() - 1) {
                extension =  fileUrl.substring(lastDotIndex + 1).toLowerCase();
            }
            // 전체 경로 구성
            Path filePath = Paths.get(saveDir, fileName+"."+extension);
            // 파일 다운로드 및 저장
            Files.copy(in, filePath, StandardCopyOption.REPLACE_EXISTING);

            System.out.println("파일 다운로드 완료: " + filePath);
        } catch (IOException e) {
            System.err.println("다운로드 실패: " + e.getMessage());
            e.printStackTrace();
        }
    }
    
}
